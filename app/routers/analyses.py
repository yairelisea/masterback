from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from .analyses_extra import process_pending

# Intentionally no prefix here; main mounts with prefix="/analyses"
router = APIRouter(tags=["analyses"])


@router.post("/ingest")
async def trigger_analyses(payload: dict, db: AsyncSession = Depends(get_session)):
    """
    Triggers processing of PENDING items for a given campaign.
    Mounted as /analyses/ingest (compatible with pipeline expectations).
    """
    campaign_id = (payload or {}).get("campaignId")
    if not campaign_id:
        raise HTTPException(status_code=400, detail="campaignId is required")
    res = await process_pending(campaignId=campaign_id, limit=200, db=db)  # type: ignore
    return res
