# app/routers/search_local.py
from __future__ import annotations

from typing import Optional, Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.db import get_session as get_db   # <— usa tu helper real (alias correcto)
from app.models import Campaign, IngestedItem
from app.services.search_local import search_local_news  # tu buscador

router = APIRouter(prefix="/search-local", tags=["search-local"])

@router.post("/campaign/{campaign_id}")
async def recover_campaign_results(
    campaign_id: str,
    session: AsyncSession = Depends(get_session),
):
    # 1) Traer campaña
    stmt = select(Campaign).where(Campaign.id == campaign_id)
    camp: Optional[Campaign] = await session.scalar(stmt)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # 2) Parámetros base (reusa lo que guardaste en la campaña)
    q = camp.query
    city = None  # si tienes city en otro campo, úsalo aquí
    country = camp.country or "MX"
    lang = camp.lang or "es-419"
    days_back = camp.days_back or 10
    limit = camp.size or 25

    # 3) Ejecutar búsqueda local
    results = await perform_local_search(
        query=q,
        city=city,
        country=country,
        lang=lang,
        days_back=days_back,
        limit=limit,
    )

    # 4) Upsert/insertar resultados en IngestedItem
    inserted = 0
    for it in results.get("items", []):
        url = it.get("url")
        title = it.get("title") or ""
        if not url:
            continue

        # Evitar duplicados por (campaignId, url)
        exists_stmt = select(IngestedItem.id).where(
            IngestedItem.campaignId == campaign_id,
            IngestedItem.url == url,
        )
        exists = await session.scalar(exists_stmt)
        if exists:
            continue

        item = IngestedItem(
            campaignId=campaign_id,
            title=title,
            url=url,
            publishedAt=None,  # si viene en it, mapéalo
        )
        session.add(item)
        inserted += 1

    await session.commit()

    return {
        "campaignId": campaign_id,
        "found": results.get("count", 0),
        "inserted": inserted,
    }