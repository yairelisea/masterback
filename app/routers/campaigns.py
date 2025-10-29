f# app/routers/campaigns.py
from __future__ import annotations
from fastapi import APIRouter, Header, HTTPException, Depends, Request, BackgroundTasks 
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session, SessionLocal
from ..models import Campaign
from ..schemas import CampaignCreate, CampaignOut
from ..deps import get_current_user
from ..services.query_builder import build_query_variants
from ..services.ingest_auto import kickoff_campaign_ingest
from .. import models, schemas
import logging

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
logger = logging.getLogger(__name__)

def _to_out(c: Campaign) -> CampaignOut:
    return CampaignOut.model_validate(c)

@router.get("", response_model=list[CampaignOut])
async def list_campaigns(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    q = select(Campaign).where(Campaign.userId == current_user["id"]).order_by(Campaign.createdAt.desc())
    rows = (await db.execute(q)).scalars().all()
    return [_to_out(c) for c in rows]

@router.post("", response_model=CampaignOut)
async def create_campaign(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: CampaignCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    ✅ Crea campaña con background task protegido
    """
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

    # ✅ WRAPPER PROTEGIDO - NUNCA rompe el servidor
    async def safe_ingest():
        """Wrapper que captura TODOS los errores"""
        try:
            logger.info(f"🚀 Starting background ingestion for campaign {campaign.id}")
            await kickoff_campaign_ingest(campaign.id)
            logger.info(f"✅ Background ingestion completed for campaign {campaign.id}")
        except Exception as e:
            logger.error(
                f"❌ Background ingestion failed for campaign {campaign.id}: {e}", 
                exc_info=True
            )
            # ✅ Opcional: guardar error en DB
            try:
                async with SessionLocal() as error_db:
                    error_campaign = await error_db.get(Campaign, campaign.id)
                    if error_campaign and hasattr(error_campaign, 'last_ingestion_error'):
                        error_campaign.last_ingestion_error = str(e)[:500]
                        await error_db.commit()
            except Exception as db_error:
                logger.error(f"Failed to save error to DB: {db_error}")

    background_tasks.add_task(safe_ingest)
    
    return _to_out(campaign)

@router.get("/{id}")
async def get_campaign_by_id(
    id: str,
    db: AsyncSession = Depends(get_session),
):
    try:
        c = await db.get(Campaign, id)
        if not c:
            raise HTTPException(status_code=404, detail="Campaign not found")
        data = CampaignOut.model_validate(c).model_dump()
        return data
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
    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if (current_user.get("role") != "admin") and (c.userId != current_user.get("id")):
        raise HTTPException(status_code=403, detail="Forbidden")

    from ..models import IngestedItem, Analysis

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

    last_item_at = (
        await db.execute(select(func.max(IngestedItem.createdAt)).where(IngestedItem.campaignId == campaign_id))
    ).scalar_one()
    last_analysis_at = (
        await db.execute(select(func.max(Analysis.createdAt)).where(Analysis.campaignId == campaign_id))
    ).scalar_one()

    return {
        "campaign": _to_out(c).model_dump(),
        "items": {"total": total_items, "by_status": counts, "last_created_at": last_item_at},
        "analyses": {"total": int(analyses_count), "last_created_at": last_analysis_at},
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
    
    # ✅ Task protegido
    async def safe_refresh():
        try:
            await kickoff_campaign_ingest(campaign_id)
        except Exception as e:
            logger.error(f"❌ Refresh failed for {campaign_id}: {e}")
    
    background_tasks.add_task(safe_refresh)
    return {"accepted": True, "campaignId": campaign_id, "mode": "async"}