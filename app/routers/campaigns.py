# app/routers/campaigns.py
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import async_session
from ..models import Campaign

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session

def _serialize_campaign(c: Campaign) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "query": c.query,
        "size": c.size,
        "days_back": c.days_back,
        "lang": c.lang,
        "country": c.country,
        "city_keywords": c.city_keywords,
        "userId": c.userId,
        "createdAt": c.createdAt.isoformat() if c.createdAt else None,
    }

@router.get("")
async def list_campaigns(
    x_user_id: str | None = Header(default=None),
    x_admin: str | None = Header(default=None),
    all: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    # Logs mínimos (puedes quitar luego)
    # print("x-user-id:", x_user_id, "x-admin:", x_admin, "all:", all)

    if x_admin == "true" or all is True:
        q = select(Campaign).order_by(Campaign.createdAt.desc())
    else:
        if not x_user_id:
            # sin user-id, devolvemos lista vacía (o puedes hacer 401)
            return []
        q = select(Campaign).where(Campaign.userId == x_user_id).order_by(Campaign.createdAt.desc())

    rows = (await db.execute(q)).scalars().all()
    return [_serialize_campaign(c) for c in rows]

@router.post("")
async def create_campaign(
    payload: dict,
    x_user_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    if not x_user_id:
        raise HTTPException(status_code=400, detail="Missing x-user-id header")

    name = payload.get("name")
    query = payload.get("query")
    if not name or not query:
        raise HTTPException(status_code=400, detail="name and query are required")

    c = Campaign(
        name=name,
        query=query,
        size=int(payload.get("size") or 25),
        days_back=int(payload.get("days_back") or 14),
        lang=payload.get("lang") or "es-419",
        country=payload.get("country") or "MX",
        city_keywords=payload.get("city_keywords"),
        userId=x_user_id,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return _serialize_campaign(c)

@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: str,
    x_user_id: str | None = Header(default=None),
    x_admin: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not (x_admin == "true" or (x_user_id and x_user_id == c.userId)):
        raise HTTPException(status_code=403, detail="Forbidden")
    return _serialize_campaign(c)