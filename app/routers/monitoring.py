# app/routers/monitoring.py
"""
Router para gestión de fuentes de monitoreo de redes sociales.
Solo accesible para usuarios admin.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, HttpUrl, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db import get_session
from app.models import (
    Campaign,
    MonitoringSource,
    AnalyticResult,
    ApifyRun,
    SocialPlatform,
    MonitoringStatus,
    RiskLevel,
)
from app.deps import get_current_user
from app.services.social_analysis_service import (
    run_campaign_monitoring_pipeline,
    get_campaign_analysis_summary,
)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


# ============================================================================
# SCHEMAS
# ============================================================================
class MonitoringSourceCreate(BaseModel):
    """Schema para crear una fuente de monitoreo"""
    url: HttpUrl
    platform: SocialPlatform
    name: Optional[str] = None


class MonitoringSourceUpdate(BaseModel):
    """Schema para actualizar una fuente de monitoreo"""
    url: Optional[HttpUrl] = None
    platform: Optional[SocialPlatform] = None
    name: Optional[str] = None
    status: Optional[MonitoringStatus] = None


class MonitoringSourceOut(BaseModel):
    """Schema de salida para fuente de monitoreo"""
    id: str
    campaignId: str
    url: str
    platform: SocialPlatform
    name: Optional[str]
    status: MonitoringStatus
    lastRunAt: Optional[datetime]
    lastRunStatus: Optional[str]
    lastRunPostsCount: Optional[int]
    totalPostsCollected: int
    errorCount: int
    createdAt: datetime

    class Config:
        from_attributes = True


class AnalyticResultOut(BaseModel):
    """Schema de salida para resultado de análisis"""
    id: str
    postUrl: Optional[str]
    postContent: Optional[str]
    postAuthor: Optional[str]
    postDate: Optional[datetime]
    likes: Optional[int]
    shares: Optional[int]
    comments: Optional[int]
    sentiment: Optional[str]
    sentimentScore: Optional[float]
    riskLevel: Optional[RiskLevel]
    riskScore: Optional[int]
    topics: Optional[List[str]]
    summary: Optional[str]
    requiresAttention: bool
    createdAt: datetime

    class Config:
        from_attributes = True


class RunPipelineRequest(BaseModel):
    """Request para ejecutar el pipeline de monitoreo"""
    days_back: int = Field(default=1, ge=1, le=30)
    max_posts_per_source: int = Field(default=50, ge=10, le=200)


class CampaignAnalysisSummary(BaseModel):
    """Resumen de análisis de campaña"""
    campaign_id: str
    period_days: int
    total_posts: int
    sentiment: dict
    risk: dict
    engagement: dict
    requires_attention: int
    generated_at: str


# ============================================================================
# ENDPOINTS - FUENTES DE MONITOREO
# ============================================================================
@router.post("/campaigns/{campaign_id}/sources", response_model=MonitoringSourceOut)
async def add_monitoring_source(
    campaign_id: str,
    source_data: MonitoringSourceCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Agrega una nueva fuente de monitoreo a una campaña.
    Solo admins pueden agregar fuentes.
    """
    # Verificar admin
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verificar que la campaña existe
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Verificar si la URL ya existe para esta campaña
    existing = await db.execute(
        select(MonitoringSource).where(
            MonitoringSource.campaignId == campaign_id,
            MonitoringSource.url == str(source_data.url),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="URL already exists for this campaign")

    # Crear fuente
    source = MonitoringSource(
        campaignId=campaign_id,
        url=str(source_data.url),
        platform=source_data.platform,
        name=source_data.name,
        status=MonitoringStatus.ACTIVE,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    return source


@router.get("/campaigns/{campaign_id}/sources", response_model=List[MonitoringSourceOut])
async def list_campaign_sources(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Lista todas las fuentes de monitoreo de una campaña.
    """
    # Verificar admin
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verificar campaña
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    result = await db.execute(
        select(MonitoringSource)
        .where(MonitoringSource.campaignId == campaign_id)
        .order_by(MonitoringSource.createdAt.desc())
    )
    sources = result.scalars().all()

    return sources


@router.get("/sources/{source_id}", response_model=MonitoringSourceOut)
async def get_monitoring_source(
    source_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Obtiene una fuente de monitoreo específica.
    """
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    source = await db.get(MonitoringSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    return source


@router.patch("/sources/{source_id}", response_model=MonitoringSourceOut)
async def update_monitoring_source(
    source_id: str,
    update_data: MonitoringSourceUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Actualiza una fuente de monitoreo.
    """
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    source = await db.get(MonitoringSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    # Actualizar campos
    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        if key == "url" and value:
            value = str(value)
        setattr(source, key, value)

    source.updatedAt = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(source)

    return source


@router.delete("/sources/{source_id}")
async def delete_monitoring_source(
    source_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Elimina una fuente de monitoreo.
    """
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    source = await db.get(MonitoringSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    await db.delete(source)
    await db.commit()

    return {"message": "Source deleted successfully", "id": source_id}


# ============================================================================
# ENDPOINTS - EJECUCIÓN DE PIPELINE
# ============================================================================
@router.post("/campaigns/{campaign_id}/run")
async def run_monitoring_pipeline(
    campaign_id: str,
    request: RunPipelineRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Ejecuta el pipeline de monitoreo para una campaña.

    NUEVO FLUJO (Ingesta Dirigida):
    1. Scraping con Apify (apify/facebook-posts-scraper)
    2. Almacena en raw_scrape_data
    3. Filtra por keywords de la campaña
    4. Análisis SOCMINT con IA
    5. Guarda en campaign_analyses

    El proceso se ejecuta en background y retorna inmediatamente.
    """
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verificar campaña
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Verificar que tiene fuentes
    sources_result = await db.execute(
        select(MonitoringSource).where(
            MonitoringSource.campaignId == campaign_id,
            MonitoringSource.status == MonitoringStatus.ACTIVE,
        )
    )
    sources = sources_result.scalars().all()

    if not sources:
        raise HTTPException(
            status_code=400,
            detail="No active monitoring sources for this campaign"
        )

    # NUEVO: Usar el sistema de Ingesta Dirigida
    from app.services.ingestion_service import run_ingestion
    from app.services.analysis_engine import process_new_data

    # Paso 1: Ejecutar ingesta (scraping y almacenamiento en raw_scrape_data)
    ingestion_result = await run_ingestion(
        db=db,
        campaign_id=campaign_id,
        max_posts=request.max_posts_per_source,
        days_back=request.days_back,
    )

    # Paso 2: Procesar datos nuevos (filtrado + análisis IA)
    analysis_result = await process_new_data(
        db=db,
        limit=request.max_posts_per_source * len(sources),
        campaign_id=campaign_id,
    )

    return {
        "status": "completed",
        "campaign_id": campaign_id,
        "ingestion": ingestion_result,
        "analysis": analysis_result,
    }


@router.get("/campaigns/{campaign_id}/summary", response_model=CampaignAnalysisSummary)
async def get_campaign_summary(
    campaign_id: str,
    days_back: int = 7,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Obtiene un resumen del análisis de una campaña.
    """
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verificar campaña
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    summary = await get_campaign_analysis_summary(
        campaign_id=campaign_id,
        db=db,
        days_back=days_back,
    )

    return summary


# ============================================================================
# ENDPOINTS - RESULTADOS DE ANÁLISIS
# ============================================================================
@router.get("/campaigns/{campaign_id}/results", response_model=List[AnalyticResultOut])
async def list_campaign_results(
    campaign_id: str,
    limit: int = 50,
    offset: int = 0,
    sentiment: Optional[str] = None,
    risk_level: Optional[RiskLevel] = None,
    requires_attention: Optional[bool] = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Lista los resultados de análisis de una campaña.
    """
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Construir query
    query = select(AnalyticResult).where(AnalyticResult.campaignId == campaign_id)

    # Filtros opcionales
    if sentiment:
        query = query.where(AnalyticResult.sentiment == sentiment)
    if risk_level:
        query = query.where(AnalyticResult.riskLevel == risk_level)
    if requires_attention is not None:
        query = query.where(AnalyticResult.requiresAttention == requires_attention)

    # Ordenar y paginar
    query = query.order_by(AnalyticResult.createdAt.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    results = result.scalars().all()

    return results


@router.get("/results/{result_id}", response_model=AnalyticResultOut)
async def get_analytic_result(
    result_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Obtiene un resultado de análisis específico.
    """
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.get(AnalyticResult, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    return result


@router.get("/results/{result_id}/raw")
async def get_analytic_result_raw(
    result_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Obtiene los datos crudos de Apify y la respuesta de IA para un resultado.
    """
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.get(AnalyticResult, result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    return {
        "id": result.id,
        "raw_apify_data": result.rawApifyData,
        "raw_ai_response": result.rawAIResponse,
    }


# ============================================================================
# ENDPOINTS - HISTORIAL DE EJECUCIONES
# ============================================================================
@router.get("/campaigns/{campaign_id}/runs")
async def list_campaign_runs(
    campaign_id: str,
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Lista el historial de ejecuciones de Apify para una campaña.
    """
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    result = await db.execute(
        select(ApifyRun)
        .where(ApifyRun.campaignId == campaign_id)
        .order_by(ApifyRun.createdAt.desc())
        .limit(limit)
    )
    runs = result.scalars().all()

    return [
        {
            "id": run.id,
            "apifyRunId": run.apifyRunId,
            "actorId": run.actorId,
            "status": run.status.value,
            "postsFound": run.postsFound,
            "postsAnalyzed": run.postsAnalyzed,
            "startedAt": run.startedAt.isoformat() if run.startedAt else None,
            "finishedAt": run.finishedAt.isoformat() if run.finishedAt else None,
            "computeUnits": run.computeUnits,
            "errorMessage": run.errorMessage,
            "createdAt": run.createdAt.isoformat(),
        }
        for run in runs
    ]


# ============================================================================
# HEALTH CHECK
# ============================================================================
@router.get("/health")
async def monitoring_health():
    """Health check del módulo de monitoreo"""
    import os

    apify_configured = bool(os.getenv("APIFY_API_TOKEN"))
    perplexity_configured = bool(os.getenv("PERPLEXITY_API_KEY"))

    return {
        "ok": True,
        "service": "Social Monitoring",
        "apify_configured": apify_configured,
        "perplexity_configured": perplexity_configured,
        "status": "ready" if (apify_configured and perplexity_configured) else "missing_config",
    }
