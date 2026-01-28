from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, HttpUrl

from fastapi import APIRouter, Header, HTTPException, Depends, Request, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from ..db import get_session, SessionLocal
from ..models import Campaign, IngestedItem, Analysis, SourceLink, ItemStatus, MonitoringSource, SocialPlatform, MonitoringStatus
from ..schemas import CampaignCreate, CampaignOut, UrlsToAnalyze, MonitoringSourceBrief
from ..deps import get_current_user
from ..services.query_builder import build_query_variants
from ..services.ingest_auto import kickoff_campaign_ingest
from ..services.perplexity_service import perplexity_service
from .. import models, schemas


# ============================================================================
# Schemas para Monitoring Sources (en campaigns router)
# ============================================================================
class AddMonitoringSourceRequest(BaseModel):
    """Request para agregar una fuente de monitoreo"""
    url: HttpUrl
    platform: str  # facebook, twitter, instagram, tiktok, youtube
    name: Optional[str] = None


class MonitoringSourceResponse(BaseModel):
    """Response de una fuente de monitoreo"""
    id: str
    campaignId: str
    url: str
    platform: str
    name: Optional[str]
    status: str
    lastRunAt: Optional[str] = None
    totalPostsCollected: int = 0
    errorCount: int = 0

    class Config:
        from_attributes = True

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _to_out(c: Campaign, monitoring_sources: list = None) -> CampaignOut:
    """Convierte un Campaign a CampaignOut incluyendo monitoring_sources"""
    data = {
        "id": c.id,
        "name": c.name,
        "query": c.query,
        "size": c.size,
        "days_back": c.days_back,
        "lang": c.lang,
        "country": c.country,
        "city_keywords": c.city_keywords,
        "plan": c.plan,
        "autoEnabled": c.autoEnabled,
        "userId": c.userId,
        "createdAt": c.createdAt,
        "news_analysis": getattr(c, "news_analysis", None),
        "monitoring_sources": None,
        "monitoring_sources_count": 0,
    }

    if monitoring_sources:
        data["monitoring_sources"] = [
            MonitoringSourceBrief(
                id=s.id,
                url=s.url,
                platform=s.platform.value if hasattr(s.platform, 'value') else str(s.platform),
                name=s.name,
                status=s.status.value if hasattr(s.status, 'value') else str(s.status),
                lastRunAt=s.lastRunAt,
                totalPostsCollected=s.totalPostsCollected or 0,
            )
            for s in monitoring_sources
        ]
        data["monitoring_sources_count"] = len(monitoring_sources)

    return CampaignOut(**data)

@router.get("", response_model=list[CampaignOut])
async def list_campaigns(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    # Cargar campañas con sus monitoring_sources usando selectinload
    # Admins pueden ver todas las campañas
    if current_user.get("role") == "admin":
        q = (
            select(Campaign)
            .options(selectinload(Campaign.monitoring_sources))
            .order_by(Campaign.createdAt.desc())
        )
    else:
        q = (
            select(Campaign)
            .options(selectinload(Campaign.monitoring_sources))
            .where(Campaign.userId == current_user["id"])
            .order_by(Campaign.createdAt.desc())
        )
    rows = (await db.execute(q)).scalars().all()
    return [_to_out(c, c.monitoring_sources) for c in rows]

async def _refresh_campaign_task(campaign_id: str):
    try:
        await kickoff_campaign_ingest(campaign_id)
    except Exception:
        # Log the error in a real application
        pass

@router.post("", response_model=CampaignOut)
async def create_campaign(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: CampaignCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    variants = build_query_variants(
        actor=payload.query,
        city_keywords=payload.city_keywords or [],
        extras=None,
    )

    campaign = Campaign(
        name=payload.name,
        query=payload.query,
        size=payload.size,
        days_back=payload.days_back,
        lang=payload.lang,
        country=payload.country,
        city_keywords=payload.city_keywords,
        search_variants=variants,
        userId=current_user["id"],
        plan=getattr(payload, "plan", "BASIC"),
        autoEnabled=getattr(payload, "autoEnabled", True),
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    # Lanza la ingesta y análisis en background
    background_tasks.add_task(kickoff_campaign_ingest, campaign.id)

    return _to_out(campaign)

@router.get("/{id}")
async def get_campaign_by_id(
    id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    try:
        # Cargar campaña con monitoring_sources
        q = (
            select(Campaign)
            .options(selectinload(Campaign.monitoring_sources))
            .where(Campaign.id == id)
        )
        result = await db.execute(q)
        c = result.scalar_one_or_none()
        if not c:
            raise HTTPException(status_code=404, detail="Campaign not found")
        # Verificar permisos: dueño o admin
        if c.userId != current_user["id"] and current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Forbidden")
        return _to_out(c, c.monitoring_sources).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e

@router.get("/{campaign_id}/items", response_model=list[schemas.IngestedItemOut])
async def list_campaign_items(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    c = await db.get(models.Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.userId != current_user["id"] and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    q = (
        select(models.IngestedItem)
        .where(models.IngestedItem.campaignId == campaign_id)
        .order_by(models.IngestedItem.createdAt.desc())
        .limit(500)
    )
    rows = (await db.execute(q)).scalars().all()
    return [schemas.IngestedItemOut.model_validate(x) for x in rows]

@router.get("/{campaign_id}/analyses", response_model=list[schemas.AnalysisOut])
async def list_campaign_analyses(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    c = await db.get(models.Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.userId != current_user["id"] and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    q = (
        select(models.Analysis)
        .where(models.Analysis.campaignId == campaign_id)
        .order_by(models.Analysis.createdAt.desc())
        .limit(500)
    )
    rows = (await db.execute(q)).scalars().all()
    return [schemas.AnalysisOut.model_validate(x) for x in rows]

@router.get("/{campaign_id}/overview")
async def campaign_overview(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    # Cargar campaña con monitoring_sources
    q = (
        select(Campaign)
        .options(selectinload(Campaign.monitoring_sources))
        .where(Campaign.id == campaign_id)
    )
    result = await db.execute(q)
    c = result.scalar_one_or_none()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if (current_user.get("role") != "admin") and (c.userId != current_user.get("id")):
        raise HTTPException(status_code=403, detail="Forbidden")

    from ..models import IngestedItem, Analysis, CampaignAnalysis

    cnt_rows = (
        await db.execute(
            select(IngestedItem.status, func.count())
            .where(IngestedItem.campaignId == campaign_id)
            .group_by(IngestedItem.status)
        )
    ).all()
    counts = {str(s[0].value if s[0] else "NONE"): int(s[1]) for s in cnt_rows}

    total_items = sum(counts.values())
    analyses_count = (
        await db.execute(select(func.count()).select_from(Analysis).where(Analysis.campaignId == campaign_id))
    ).scalar_one()

    # Nuevo: Contar análisis de SOCMINT
    socmint_count = (
        await db.execute(select(func.count()).select_from(CampaignAnalysis).where(CampaignAnalysis.campaignId == campaign_id))
    ).scalar_one()

    last_item_at = (
        await db.execute(select(func.max(IngestedItem.createdAt)).where(IngestedItem.campaignId == campaign_id))
    ).scalar_one()
    last_analysis_at = (
        await db.execute(select(func.max(Analysis.createdAt)).where(Analysis.campaignId == campaign_id))
    ).scalar_one()
    last_socmint_at = (
        await db.execute(select(func.max(CampaignAnalysis.analyzedAt)).where(CampaignAnalysis.campaignId == campaign_id))
    ).scalar_one()

    return {
        "campaign": _to_out(c, c.monitoring_sources).model_dump(),
        "items": {"total": total_items, "by_status": counts, "last_created_at": last_item_at},
        "analyses": {"total": int(analyses_count), "last_created_at": last_analysis_at},
        "socmint": {"total": int(socmint_count), "last_created_at": last_socmint_at},
    }

@router.post("/{campaign_id}/refresh")
async def refresh_campaign(
    campaign_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if (current_user.get("role") != "admin") and (c.userId != current_user.get("id")):
        raise HTTPException(status_code=403, detail="Forbidden")
    background_tasks.add_task(_refresh_campaign_task, campaign_id)
    return {"accepted": True, "campaignId": campaign_id, "mode": "async"}

@router.post("/{campaign_id}/urls")
async def add_urls_to_campaign(
    campaign_id: str,
    payload: UrlsToAnalyze,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if (current_user.get("role") != "admin") and (c.userId != current_user.get("id")):
        raise HTTPException(status_code=403, detail="Forbidden")

    analyzed_items = await perplexity_service.analyze_urls(
        urls=[str(url) for url in payload.urls],
        campaign_name=c.name,
    )

    for item_data in analyzed_items:
        source_link = SourceLink(
            campaignId=c.id,
            url=item_data["url"],
        )
        ingested_item = IngestedItem(
            campaignId=c.id,
            sourceId=source_link.id,
            title=item_data["title"],
            url=item_data["url"],
            publishedAt=item_data.get("publishedAt"),
            status=ItemStatus.PROCESSED,
        )
        analysis = Analysis(
            campaignId=c.id,
            itemId=ingested_item.id,
            sentiment=item_data.get("sentiment_score"),
            tone=item_data.get("sentiment_label"),
            topics=item_data.get("topics", []),
            summary=item_data.get("summary", ""),
        )
        ingested_item.analysis = analysis
        db.add(source_link)
        db.add(ingested_item)

    await db.commit()

    return {"accepted": True, "processed_items": len(analyzed_items)}


# ============================================================================
# ENDPOINTS - Fuentes de Monitoreo de Redes Sociales (SOLO ADMIN)
# ============================================================================
@router.get("/{campaign_id}/monitoring-sources", response_model=list[MonitoringSourceResponse])
async def list_campaign_monitoring_sources(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Lista todas las fuentes de monitoreo de una campaña.
    Permite ver las URLs de Facebook, Twitter, Instagram, etc. configuradas.

    **Solo accesible para administradores.**
    """
    # Solo admins pueden acceder (verificar role o isAdmin)
    if current_user.get("role") != "admin" and not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")

    q = (
        select(MonitoringSource)
        .where(MonitoringSource.campaignId == campaign_id)
        .order_by(MonitoringSource.createdAt.desc())
    )
    result = await db.execute(q)
    sources = result.scalars().all()

    return [
        MonitoringSourceResponse(
            id=s.id,
            campaignId=s.campaignId,
            url=s.url,
            platform=s.platform.value if hasattr(s.platform, 'value') else str(s.platform),
            name=s.name,
            status=s.status.value if hasattr(s.status, 'value') else str(s.status),
            lastRunAt=s.lastRunAt.isoformat() if s.lastRunAt else None,
            totalPostsCollected=s.totalPostsCollected or 0,
            errorCount=s.errorCount or 0,
        )
        for s in sources
    ]


@router.post("/{campaign_id}/monitoring-sources", response_model=MonitoringSourceResponse)
async def add_monitoring_source(
    campaign_id: str,
    payload: AddMonitoringSourceRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Agrega una nueva fuente de monitoreo a una campaña.

    **Solo accesible para administradores.**

    Plataformas soportadas:
    - **facebook**: Páginas de Facebook
    - **twitter**: Cuentas de Twitter/X
    - **instagram**: Perfiles de Instagram
    - **tiktok**: Cuentas de TikTok
    - **youtube**: Canales de YouTube
    - **news_site**: Sitios de noticias locales (El Sol de Tampico, La Razón, Milenio, etc.)

    Ejemplos de uso:

    **Red social:**
    ```json
    {
        "url": "https://www.facebook.com/JuanPerezOficial",
        "platform": "facebook",
        "name": "Página oficial de Juan Pérez"
    }
    ```

    **Medio de noticias:**
    ```json
    {
        "url": "https://www.elsoldetampico.com.mx/local",
        "platform": "news_site",
        "name": "El Sol de Tampico - Local"
    }
    ```
    """
    # Solo admins pueden agregar fuentes (verificar role o isAdmin)
    if current_user.get("role") != "admin" and not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verificar campaña
    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Validar plataforma
    platform_lower = payload.platform.lower()
    valid_platforms = ["facebook", "twitter", "instagram", "tiktok", "youtube", "news_site"]
    if platform_lower not in valid_platforms:
        raise HTTPException(
            status_code=400,
            detail=f"Plataforma no válida. Usa una de: {', '.join(valid_platforms)}"
        )

    # Verificar si la URL ya existe para esta campaña
    existing = await db.execute(
        select(MonitoringSource).where(
            MonitoringSource.campaignId == campaign_id,
            MonitoringSource.url == str(payload.url),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Esta URL ya está registrada para esta campaña")

    # Mapear string a enum
    platform_enum = SocialPlatform(platform_lower)

    # Crear fuente
    source = MonitoringSource(
        campaignId=campaign_id,
        url=str(payload.url),
        platform=platform_enum,
        name=payload.name,
        status=MonitoringStatus.ACTIVE,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    return MonitoringSourceResponse(
        id=source.id,
        campaignId=source.campaignId,
        url=source.url,
        platform=source.platform.value,
        name=source.name,
        status=source.status.value,
        lastRunAt=None,
        totalPostsCollected=0,
        errorCount=0,
    )


@router.delete("/{campaign_id}/monitoring-sources/{source_id}")
async def delete_monitoring_source(
    campaign_id: str,
    source_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Elimina una fuente de monitoreo de una campaña.

    **Solo accesible para administradores.**
    """
    # Solo admins pueden eliminar fuentes (verificar role o isAdmin)
    if current_user.get("role") != "admin" and not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    # Verificar campaña
    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Verificar fuente
    source = await db.get(MonitoringSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    if source.campaignId != campaign_id:
        raise HTTPException(status_code=400, detail="Source does not belong to this campaign")

    await db.delete(source)
    await db.commit()

    return {"message": "Fuente eliminada correctamente", "id": source_id}
