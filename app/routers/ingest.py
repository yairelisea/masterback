from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db import get_session
from ..models import Campaign, IngestedItem, ItemStatus

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("", status_code=200)
async def ingest(payload: dict, session: AsyncSession = Depends(get_session)):
    """
    No-op compatible endpoint to align with the pipeline.
    Ensures that any items for the campaign with NULL status are marked as PENDING.
    Path is mounted as /ingest/ingest due to include_router(prefix="/ingest").
    """
    campaign_id = (payload or {}).get("campaignId")
    if not campaign_id:
        raise HTTPException(status_code=400, detail="campaignId is required")

    camp = await session.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="campaign not found")

    # Normalize status for any items that were persisted without status
    rows = (
        await session.execute(
            select(IngestedItem).where(
                IngestedItem.campaignId == campaign_id,
                IngestedItem.status == None,  # noqa: E711
            )
        )
    ).scalars().all()
    updated = 0
    for it in rows:
        it.status = ItemStatus.PENDING
        updated += 1
    if updated:
        await session.commit()

    return {"ok": True, "campaignId": campaign_id, "normalized": updated}
