from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import load_only
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from ..deps import get_current_user
from ..models import Campaign, IngestedItem, Analysis
from ..schemas import IngestedItemOut, AnalysisOut

router = APIRouter(prefix="", tags=["items"])

async def _ensure_owner(campaign_id: str, user: dict, db: AsyncSession) -> Campaign:
    camp = await db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if (user.get("role") != "admin") and (camp.userId != user["id"]):
        raise HTTPException(status_code=403, detail="Forbidden")
    return camp

@router.get("/campaigns/{campaign_id}/items", response_model=list[IngestedItemOut])
async def list_items(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    await _ensure_owner(campaign_id, current_user, db)
    q = (
        select(IngestedItem)
        .where(IngestedItem.campaignId == campaign_id)
        .order_by(IngestedItem.createdAt.desc())
        .limit(500)
    )
    rows = (await db.execute(q)).scalars().all()
    return [IngestedItemOut.model_validate(r) for r in rows]

@router.get("/campaigns/{campaign_id}/analyses", response_model=list[AnalysisOut])
async def list_analyses(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    await _ensure_owner(campaign_id, current_user, db)
    q = (
        select(Analysis)
        .options(
            load_only(
                Analysis.id,
                Analysis.campaignId,
                Analysis.itemId,
                Analysis.sentiment,
                Analysis.tone,
                Analysis.topics,
                Analysis.summary,
                Analysis.entities,
                Analysis.stance,
                Analysis.perception,
                Analysis.createdAt,
            )
        )
        .where(Analysis.campaignId == campaign_id)
        .order_by(Analysis.createdAt.desc())
        .limit(500)
    )
    rows = (await db.execute(q)).scalars().all()
    return [AnalysisOut.model_validate(r) for r in rows]
