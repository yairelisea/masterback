from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid, hashlib

from ..db import get_session
from .. import models, schemas

router = APIRouter(prefix="/ingest", tags=["ingest"])

@router.post("", status_code=201)
async def ingest(payload: schemas.IngestCreate, session: AsyncSession = Depends(get_session)):
    # validate campaign
    cres = await session.execute(select(models.Campaign).where(models.Campaign.id == payload.campaignId))
    if not cres.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="campaign not found")

    h = hashlib.sha256(str(payload.contentUrl).encode()).hexdigest()
    dup = await session.execute(select(models.IngestedItem).where(models.IngestedItem.hash == h))
    if dup.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="item already ingested")

    item = models.IngestedItem(
        id=str(uuid.uuid4()),
        campaignId=payload.campaignId,
        sourceType=models.SourceType(payload.sourceType),
        sourceUrl=str(payload.sourceUrl),
        contentUrl=str(payload.contentUrl),
        author=payload.author,
        title=payload.title,
        excerpt=payload.excerpt,
        publishedAt=payload.publishedAt,
        status=models.ItemStatus.QUEUED,
        hash=h
    )
    session.add(item)
    await session.commit()
    return {"id": item.id, "status": item.status}