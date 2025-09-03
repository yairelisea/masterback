from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from .. import models, schemas
from ..models import Campaign, User
from ..schemas import CampaignCreate, CampaignOut

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _to_out(c: Campaign) -> CampaignOut:
    # gracias a from_attributes=True en CampaignOut
    return CampaignOut.model_validate(c)


# ------------------------
# List campaigns
# ------------------------
@router.get("", response_model=list[CampaignOut])
async def list_campaigns(
    request: Request,
    x_user_id: str | None = Header(default=None),
    x_admin: str | None = Header(default=None),
    all: bool | None = None,
    db: AsyncSession = Depends(get_session),
):
    if x_admin == "true" or all is True:
        q = select(Campaign).order_by(Campaign.createdAt.desc())
    else:
        if not x_user_id:
            return []
        q = (
            select(Campaign)
            .where(Campaign.userId == x_user_id)
            .order_by(Campaign.createdAt.desc())
        )

    rows = (await db.execute(q)).scalars().all()
    return [_to_out(c) for c in rows]


# ------------------------
# Create campaign
# ------------------------
@router.post("", response_model=CampaignOut)
async def create_campaign(
    payload: CampaignCreate,
    request: Request,
    x_user_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session),
):
    if not x_user_id:
        raise HTTPException(status_code=400, detail="Missing x-user-id header")

    # 1) Asegura que exista el usuario
    result = await db.execute(select(User).where(User.id == x_user_id))
    user = result.scalar_one_or_none()

    if not user:
        user = User(
            id=x_user_id,
            email=f"{x_user_id}@example.com",
            name=x_user_id,
        )
        db.add(user)
        await db.flush()

    # 2) Crea la campaña
    campaign = Campaign(
        name=payload.name,
        query=payload.query,
        size=payload.size,
        days_back=payload.days_back,
        lang=payload.lang,
        country=payload.country,
        city_keywords=payload.city_keywords,
        userId=x_user_id,
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