# app/routers/ingestion.py
"""
API Router para el sistema de Ingesta Dirigida.

Endpoints para:
- Ejecutar ingesta de fuentes de monitoreo
- Procesar nuevos datos (Momento A)
- Ejecutar retro-análisis de campañas (Momento B)
- Consultar resultados de análisis
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import datetime, timezone

from ..db import get_session
from ..models import (
    RawScrapeData, CampaignAnalysis, Campaign, MonitoringSource,
    AnalysisRiskLevel
)
from ..services.ingestion_service import IngestionService, run_ingestion
from ..services.analysis_engine import AnalysisEngine, process_new_data, run_campaign_backfill

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


# =========================================================================
# ENDPOINTS DE INGESTA
# =========================================================================

@router.post("/run")
async def trigger_ingestion(
    background_tasks: BackgroundTasks,
    campaign_id: Optional[str] = Query(None, description="ID de campaña específica (opcional)"),
    max_posts: int = Query(100, ge=10, le=500, description="Máximo posts por fuente"),
    days_back: int = Query(7, ge=1, le=30, description="Días hacia atrás"),
    async_mode: bool = Query(True, description="Ejecutar en background"),
    db: AsyncSession = Depends(get_session)
):
    """
    Ejecuta el flujo de ingesta de datos desde las fuentes de monitoreo.

    1. Consulta MonitoringSources activas
    2. Ejecuta el Actor de Apify (alien_force/facebook-scraper-pro)
    3. Almacena resultados en RawScrapeData

    Si async_mode=True, la ingesta se ejecuta en background y retorna inmediatamente.
    """
    if async_mode:
        # Ejecutar en background
        background_tasks.add_task(
            _run_ingestion_task,
            campaign_id=campaign_id,
            max_posts=max_posts,
            days_back=days_back
        )
        return {
            "status": "started",
            "message": "Ingesta iniciada en background",
            "params": {
                "campaign_id": campaign_id,
                "max_posts": max_posts,
                "days_back": days_back
            }
        }
    else:
        # Ejecutar síncronamente
        result = await run_ingestion(
            db=db,
            campaign_id=campaign_id,
            max_posts=max_posts,
            days_back=days_back
        )
        return result


async def _run_ingestion_task(campaign_id: Optional[str], max_posts: int, days_back: int):
    """Task de background para ingesta"""
    from ..db import async_session_maker

    async with async_session_maker() as db:
        try:
            await run_ingestion(
                db=db,
                campaign_id=campaign_id,
                max_posts=max_posts,
                days_back=days_back
            )
        except Exception as e:
            print(f"❌ Error en ingesta background: {e}")


# =========================================================================
# ENDPOINTS DE ANÁLISIS (MOMENTO A)
# =========================================================================

@router.post("/process")
async def process_pending_data(
    background_tasks: BackgroundTasks,
    campaign_id: Optional[str] = Query(None, description="Campaña específica (opcional)"),
    limit: int = Query(100, ge=10, le=500, description="Máximo registros a procesar"),
    async_mode: bool = Query(True, description="Ejecutar en background"),
    db: AsyncSession = Depends(get_session)
):
    """
    MOMENTO A: Procesa datos pendientes en RawScrapeData.

    Busca palabras clave de las campañas y envía a análisis de IA
    los posts que coincidan.
    """
    if async_mode:
        background_tasks.add_task(
            _process_data_task,
            campaign_id=campaign_id,
            limit=limit
        )
        return {
            "status": "started",
            "message": "Procesamiento iniciado en background",
            "params": {
                "campaign_id": campaign_id,
                "limit": limit
            }
        }
    else:
        result = await process_new_data(
            db=db,
            limit=limit,
            campaign_id=campaign_id
        )
        return result


async def _process_data_task(campaign_id: Optional[str], limit: int):
    """Task de background para procesamiento"""
    from ..db import async_session_maker

    async with async_session_maker() as db:
        try:
            await process_new_data(
                db=db,
                limit=limit,
                campaign_id=campaign_id
            )
        except Exception as e:
            print(f"❌ Error en procesamiento background: {e}")


# =========================================================================
# ENDPOINTS DE RETRO-ANÁLISIS (MOMENTO B)
# =========================================================================

@router.post("/backfill/{campaign_id}")
async def trigger_backfill(
    campaign_id: str,
    background_tasks: BackgroundTasks,
    limit: int = Query(1000, ge=100, le=5000, description="Máximo registros históricos"),
    async_mode: bool = Query(True, description="Ejecutar en background"),
    db: AsyncSession = Depends(get_session)
):
    """
    MOMENTO B: Retro-análisis para una campaña.

    Busca en TODO el histórico de RawScrapeData coincidencias con
    las palabras clave del candidato y ejecuta análisis de IA.

    Útil cuando:
    - Se crea una nueva campaña
    - Se agregan nuevas palabras clave a una campaña existente
    """
    # Verificar que la campaña existe
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")

    if async_mode:
        background_tasks.add_task(
            _backfill_task,
            campaign_id=campaign_id,
            limit=limit
        )
        return {
            "status": "started",
            "message": f"Retro-análisis iniciado para '{campaign.name}'",
            "params": {
                "campaign_id": campaign_id,
                "campaign_name": campaign.name,
                "query": campaign.query,
                "limit": limit
            }
        }
    else:
        result = await run_campaign_backfill(
            db=db,
            campaign_id=campaign_id,
            limit=limit
        )
        return result


async def _backfill_task(campaign_id: str, limit: int):
    """Task de background para backfill"""
    from ..db import async_session_maker

    async with async_session_maker() as db:
        try:
            await run_campaign_backfill(
                db=db,
                campaign_id=campaign_id,
                limit=limit
            )
        except Exception as e:
            print(f"❌ Error en backfill background: {e}")


# =========================================================================
# ENDPOINTS DE CONSULTA
# =========================================================================

@router.get("/stats")
async def get_ingestion_stats(
    db: AsyncSession = Depends(get_session)
):
    """
    Estadísticas generales del sistema de ingesta.
    """
    # Total de datos crudos
    raw_total = await db.execute(select(func.count(RawScrapeData.id)))
    raw_count = raw_total.scalar() or 0

    # Datos pendientes de procesar
    raw_pending = await db.execute(
        select(func.count(RawScrapeData.id)).where(RawScrapeData.isProcessed == False)
    )
    pending_count = raw_pending.scalar() or 0

    # Total de análisis
    analysis_total = await db.execute(select(func.count(CampaignAnalysis.id)))
    analysis_count = analysis_total.scalar() or 0

    # Análisis por nivel de riesgo
    risk_stats = await db.execute(
        select(CampaignAnalysis.riskLevel, func.count(CampaignAnalysis.id))
        .group_by(CampaignAnalysis.riskLevel)
    )
    risk_by_level = {str(r[0].value) if r[0] else "unknown": r[1] for r in risk_stats.fetchall()}

    # Fuentes activas
    sources_total = await db.execute(select(func.count(MonitoringSource.id)))
    sources_count = sources_total.scalar() or 0

    return {
        "raw_scrape_data": {
            "total": raw_count,
            "pending": pending_count,
            "processed": raw_count - pending_count
        },
        "campaign_analyses": {
            "total": analysis_count,
            "by_risk_level": risk_by_level
        },
        "monitoring_sources": {
            "total": sources_count
        }
    }


@router.get("/raw-data")
async def list_raw_data(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    is_processed: Optional[bool] = Query(None),
    platform: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_session)
):
    """
    Lista datos crudos en RawScrapeData.
    """
    query = select(RawScrapeData).order_by(desc(RawScrapeData.createdAt))

    if is_processed is not None:
        query = query.where(RawScrapeData.isProcessed == is_processed)

    if platform:
        query = query.where(RawScrapeData.platform == platform)

    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "count": len(items),
        "items": [
            {
                "id": item.id,
                "post_url": item.postUrl,
                "raw_text": (item.rawText or "")[:300] + "..." if item.rawText and len(item.rawText) > 300 else item.rawText,
                "post_date": item.postDate.isoformat() if item.postDate else None,
                "post_author": item.postAuthor,
                "platform": item.platform,
                "likes": item.likes,
                "shares": item.shares,
                "comments": item.comments,
                "is_processed": item.isProcessed,
                "created_at": item.createdAt.isoformat()
            }
            for item in items
        ]
    }


@router.get("/analyses")
async def list_analyses(
    campaign_id: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_session)
):
    """
    Lista resultados de análisis (CampaignAnalysis).
    """
    from sqlalchemy.orm import selectinload

    query = (
        select(CampaignAnalysis)
        .options(selectinload(CampaignAnalysis.raw_data))
        .order_by(desc(CampaignAnalysis.analyzedAt))
    )

    if campaign_id:
        query = query.where(CampaignAnalysis.campaignId == campaign_id)

    if risk_level:
        query = query.where(CampaignAnalysis.riskLevel == risk_level)

    if category:
        query = query.where(CampaignAnalysis.category == category)

    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    items = result.scalars().all()

    return {
        "count": len(items),
        "items": [
            {
                "id": item.id,
                "campaign_id": item.campaignId,
                "sentiment_score": item.sentimentScore,
                "category": item.category.value if item.category else None,
                "risk_level": item.riskLevel.value if item.riskLevel else None,
                "summary": item.summary,
                "intent": item.intent.value if item.intent else None,
                "matched_keywords": item.matchedKeywords,
                "analyzed_at": item.analyzedAt.isoformat(),
                "raw_data": {
                    "post_url": item.raw_data.postUrl if item.raw_data else None,
                    "raw_text": (item.raw_data.rawText or "")[:200] + "..." if item.raw_data and item.raw_data.rawText and len(item.raw_data.rawText) > 200 else (item.raw_data.rawText if item.raw_data else None),
                    "post_author": item.raw_data.postAuthor if item.raw_data else None,
                    "post_date": item.raw_data.postDate.isoformat() if item.raw_data and item.raw_data.postDate else None,
                }
            }
            for item in items
        ]
    }


@router.get("/analyses/{campaign_id}/dashboard")
async def get_campaign_analysis_dashboard(
    campaign_id: str,
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_session)
):
    """
    Dashboard de análisis para una campaña específica.

    Incluye:
    - Resumen de sentimiento
    - Distribución por categoría
    - Posts de alto riesgo
    - Tendencias
    """
    from datetime import timedelta

    # Verificar campaña
    campaign_result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = campaign_result.scalar_one_or_none()

    if not campaign:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    # Total de análisis
    total_query = await db.execute(
        select(func.count(CampaignAnalysis.id)).where(
            CampaignAnalysis.campaignId == campaign_id,
            CampaignAnalysis.analyzedAt >= cutoff_date
        )
    )
    total_count = total_query.scalar() or 0

    # Promedio de sentimiento
    sentiment_avg = await db.execute(
        select(func.avg(CampaignAnalysis.sentimentScore)).where(
            CampaignAnalysis.campaignId == campaign_id,
            CampaignAnalysis.analyzedAt >= cutoff_date
        )
    )
    avg_sentiment = sentiment_avg.scalar() or 0

    # Distribución por riesgo
    risk_dist = await db.execute(
        select(CampaignAnalysis.riskLevel, func.count(CampaignAnalysis.id))
        .where(
            CampaignAnalysis.campaignId == campaign_id,
            CampaignAnalysis.analyzedAt >= cutoff_date
        )
        .group_by(CampaignAnalysis.riskLevel)
    )
    risk_distribution = {str(r[0].value) if r[0] else "unknown": r[1] for r in risk_dist.fetchall()}

    # Distribución por categoría
    cat_dist = await db.execute(
        select(CampaignAnalysis.category, func.count(CampaignAnalysis.id))
        .where(
            CampaignAnalysis.campaignId == campaign_id,
            CampaignAnalysis.analyzedAt >= cutoff_date
        )
        .group_by(CampaignAnalysis.category)
    )
    category_distribution = {str(c[0].value) if c[0] else "unknown": c[1] for c in cat_dist.fetchall()}

    # Posts de alto riesgo recientes
    high_risk = await db.execute(
        select(CampaignAnalysis)
        .options(selectinload(CampaignAnalysis.raw_data))
        .where(
            CampaignAnalysis.campaignId == campaign_id,
            CampaignAnalysis.riskLevel.in_([AnalysisRiskLevel.ALTO, AnalysisRiskLevel.CRITICO]),
            CampaignAnalysis.analyzedAt >= cutoff_date
        )
        .order_by(desc(CampaignAnalysis.analyzedAt))
        .limit(10)
    )
    high_risk_items = high_risk.scalars().all()

    return {
        "campaign": {
            "id": campaign.id,
            "name": campaign.name,
            "query": campaign.query
        },
        "period": {
            "days": days,
            "from": cutoff_date.isoformat(),
            "to": datetime.now(timezone.utc).isoformat()
        },
        "summary": {
            "total_analyses": total_count,
            "avg_sentiment": round(float(avg_sentiment), 3),
            "sentiment_label": "Positivo" if avg_sentiment > 0.2 else ("Negativo" if avg_sentiment < -0.2 else "Neutral")
        },
        "risk_distribution": risk_distribution,
        "category_distribution": category_distribution,
        "high_risk_items": [
            {
                "id": item.id,
                "summary": item.summary,
                "risk_level": item.riskLevel.value if item.riskLevel else None,
                "category": item.category.value if item.category else None,
                "intent": item.intent.value if item.intent else None,
                "sentiment_score": item.sentimentScore,
                "post_url": item.raw_data.postUrl if item.raw_data else None,
                "post_author": item.raw_data.postAuthor if item.raw_data else None,
                "analyzed_at": item.analyzedAt.isoformat()
            }
            for item in high_risk_items
        ]
    }
