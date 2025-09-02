from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from ..db import get_session
from .. import models, schemas

router = APIRouter(prefix="/campaigns/{campaign_id}/sources", tags=["sources"])

@router.post("", status_code=201)
async def add_source(
    payload: schemas.SourceCreate,
    campaign_id: str = Path(...),
    session: AsyncSession = Depends(get_session),
):
    # validate campaign exists
    cres = await session.execute(select(models.Campaign).where(models.Campaign.id == campaign_id))
    camp = cres.scalar_one_or_none()
    if not camp:
        raise HTTPException(status_code=404, detail="campaign not found")

    # unique per (campaignId, url)
    dup = await session.execute(
        select(models.SourceLink).where(models.SourceLink.campaignId == campaign_id, models.SourceLink.url == str(payload.url))
    )
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="source already exists for this campaign/url")

    src = models.SourceLink(
        id=str(uuid.uuid4()),
        campaignId=campaign_id,
        type=models.SourceType(payload.type),
        url=str(payload.url),
        label=payload.label,
        isActive=True
    )
    session.add(src)
    await session.commit()
    return {"id": src.id, "type": src.type, "url": src.url, "label": src.label}