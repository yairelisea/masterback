from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Depends, Request, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from .. import models, schemas
from ..models import Campaign, User
from ..schemas import CampaignCreate, CampaignOut
from ..deps import get_current_user
from ..services.ingest_auto import kickoff_campaign_ingest

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _to_out(c: Campaign) -> CampaignOut:
    # gracias a from_attributes=True en CampaignOut
    return CampaignOut.model_validate(c)


# ------------------------
# List campaigns
# ------------------------
@router.get("", response_model=list[CampaignOut])
async def list_campaigns(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    q = select(Campaign).where(Campaign.userId == current_user["id"]).order_by(Campaign.createdAt.desc())
    rows = (await db.execute(q)).scalars().all()
    return [_to_out(c) for c in rows]


# ------------------------
# Create campaign
# ------------------------
@router.post("", response_model=CampaignOut)
async def create_campaign(
    payload: CampaignCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    # usuario viene del token; garantizado en /auth/login ya lo creamos si no existe
    campaign = Campaign(
        name=payload.name,
        query=payload.query,
        size=payload.size,
        days_back=payload.days_back,
        lang=payload.lang,
        country=payload.country,
        city_keywords=payload.city_keywords,
        plan=models.PlanTier(payload.plan.value) if hasattr(payload.plan, 'value') else models.PlanTier(payload.plan),
        autoEnabled=payload.autoEnabled,
        userId=current_user["id"],
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return _to_out(campaign)


# ------------------------
# Get campaign by ID
# ------------------------
@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(
    campaign_id: str,
    x_user_id: str | None = Header(default=None),
    x_admin: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session),
):
    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if not (x_admin == "true" or (x_user_id and x_user_id == c.userId)):
        raise HTTPException(status_code=403, detail="Forbidden")

    return _to_out(c)