
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from ..db import get_session
from .. import models, schemas
from ..deps import get_current_user

router = APIRouter(prefix="/admin", tags=["admin"])

def _require_admin(current_user: dict):
    if not current_user or not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin only")

# ------------- Users -------------
@router.get("/users", response_model=List[schemas.AdminUserOut])
async def list_users(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    _require_admin(current_user)
    res = await db.execute(select(models.User))
    return [schemas.AdminUserOut.model_validate(u) for u in res.scalars().all()]

@router.post("/users", response_model=schemas.AdminUserOut, status_code=201)
async def create_user(payload: schemas.AdminUserCreate, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    _require_admin(current_user)
    if await db.get(models.User, payload.id):
        raise HTTPException(status_code=400, detail="User id already exists")
    u = models.User(id=payload.id, email=payload.email, name=payload.name)
    u.isAdmin = payload.isAdmin
    u.plan = models.PlanTier(payload.plan.value if hasattr(payload.plan, "value") else payload.plan)
    u.features = payload.features or {}
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return schemas.AdminUserOut.model_validate(u)

@router.patch("/users/{user_id}", response_model=schemas.AdminUserOut)
async def update_user(user_id: str, payload: schemas.AdminUserUpdate, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    _require_admin(current_user)
    u = await db.get(models.User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.name is not None: u.name = payload.name
    if payload.isAdmin is not None: u.isAdmin = payload.isAdmin
    if payload.plan is not None: u.plan = models.PlanTier(payload.plan.value if hasattr(payload.plan, "value") else payload.plan)
    if payload.features is not None: u.features = payload.features
    await db.commit()
    await db.refresh(u)
    return schemas.AdminUserOut.model_validate(u)

# ------------- Campaigns -------------
@router.get("/campaigns", response_model=List[schemas.CampaignOut])
async def admin_list_campaigns(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    _require_admin(current_user)
    res = await db.execute(select(models.Campaign).order_by(models.Campaign.createdAt.desc()))
    return [schemas.CampaignOut.model_validate(c) for c in res.scalars().all()]

@router.post("/campaigns", response_model=schemas.CampaignOut, status_code=201)
async def admin_create_campaign(payload: schemas.CampaignCreate, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    _require_admin(current_user)
    c = models.Campaign(
        name=payload.name,
        query=payload.query,
        size=payload.size,
        days_back=payload.days_back,
        lang=payload.lang,
        country=payload.country,
        city_keywords=payload.city_keywords,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return schemas.CampaignOut.model_validate(c)

@router.patch("/campaigns/{campaign_id}", response_model=schemas.CampaignOut)
async def admin_update_campaign(campaign_id: str, payload: schemas.CampaignUpdate, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    _require_admin(current_user)
    c = await db.get(models.Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if payload.name is not None: c.name = payload.name
    if payload.query is not None: c.query = payload.query
    if payload.size is not None: c.size = payload.size
    if payload.days_back is not None: c.days_back = payload.days_back
    if payload.lang is not None: c.lang = payload.lang
    if payload.country is not None: c.country = payload.country
    if payload.city_keywords is not None: c.city_keywords = payload.city_keywords
    if payload.plan is not None: c.plan = models.PlanTier(payload.plan.value if hasattr(payload.plan, "value") else payload.plan)
    if payload.autoEnabled is not None: c.autoEnabled = payload.autoEnabled
    await db.commit()
    await db.refresh(c)
    return schemas.CampaignOut.model_validate(c)

# ------------- Manual URLs (attach to campaign) -------------
@router.post("/campaigns/{campaign_id}/urls", status_code=201)
async def admin_add_campaign_url(campaign_id: str, payload: schemas.SourceCreate, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    _require_admin(current_user)
    c = await db.get(models.Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    s = models.SourceLink(
        campaignId=campaign_id,
        type=models.SourceType.NEWS if payload.type.value == "NEWS" else models.SourceType(payload.type.value),
        url=payload.url
    )
    db.add(s)
    await db.commit()
    return {"ok": True, "id": s.id}
