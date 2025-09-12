from __future__ import annotations
from fastapi import APIRouter, Header, HTTPException, Depends, Request, BackgroundTasks 
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from ..models import Campaign
from ..schemas import CampaignCreate, CampaignOut
from ..deps import get_current_user
from ..services.query_builder import build_query_variants

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

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

async def _safe_pipeline(token: str, campaign_id: str):
    try:
        from ..services.pipeline import run_gn_local_analyses
        await run_gn_local_analyses(token, campaign_id)
    except Exception:
        pass

@router.post("", response_model=CampaignOut)
async def create_campaign(
    request: Request,
    background_tasks: BackgroundTasks,
    payload: CampaignCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    # Genera variantes de búsqueda
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

    # Lanza pipeline GN + Local + Analyses en background
    try:
        auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
        token = auth_header.split(" ", 1)[1].strip() if auth_header.lower().startswith("bearer ") else ""
        if token:
            from ..services.pipeline import run_gn_local_analyses
            background_tasks.add_task(run_gn_local_analyses, token, campaign.id)
    except Exception:
        pass

    return _to_out(campaign)

@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    # Permite ver si es dueño o admin
    if (current_user.get("role") != "admin") and (c.userId != current_user.get("id")):
        raise HTTPException(status_code=403, detail="Forbidden")
    return _to_out(c)


@router.get("/{campaign_id}/overview")
async def campaign_overview(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Compat: resumen de campaña (alias de admin overview) accesible para el dueño o admin.
    Devuelve totales de items por status y totales de analyses.
    """
    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if (current_user.get("role") != "admin") and (c.userId != current_user.get("id")):
        raise HTTPException(status_code=403, detail="Forbidden")

    from ..models import IngestedItem, Analysis

    # Items por status
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
