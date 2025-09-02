from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from ..db import get_session
from .. import models, schemas

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

@router.get("")
async def list_campaigns(session: AsyncSession = Depends(get_session)):
    stmt = select(models.Campaign).order_by(models.Campaign.createdAt.desc())
    res = await session.execute(stmt)
    campaigns = res.scalars().all()
    # eager sources
    out = []
    for c in campaigns:
        sources_stmt = select(models.SourceLink).where(models.SourceLink.campaignId == c.id)
        sres = await session.execute(sources_stmt)
        sources = sres.scalars().all()
        out.append({
            "id": c.id, "name": c.name, "slug": c.slug, "description": c.description,
            "ownerId": c.ownerId, "createdAt": c.createdAt, "updatedAt": c.updatedAt,
            "sources": [ { "id": s.id, "type": s.type, "label": s.label, "url": s.url, "isActive": s.isActive } for s in sources ]
        })
    return out

@router.post("", status_code=201)
async def create_campaign(payload: schemas.CampaignCreate, session: AsyncSession = Depends(get_session)):
    # upsert owner by email
    stmt_user = select(models.User).where(models.User.email == payload.ownerEmail)
    res = await session.execute(stmt_user)
    user = res.scalar_one_or_none()
    if not user:
        user = models.User(id=str(uuid.uuid4()), email=payload.ownerEmail, name=payload.ownerEmail.split("@")[0])
        session.add(user)
        await session.flush()

    # unique slug
    check = await session.execute(select(models.Campaign).where(models.Campaign.slug == payload.slug))
    if check.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="slug ya existe")

    camp = models.Campaign(
        id=str(uuid.uuid4()),
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        ownerId=user.id,
    )
    session.add(camp)
    await session.commit()
    return {"id": camp.id, "name": camp.name, "slug": camp.slug}