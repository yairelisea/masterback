# app/routers/search_local.py
from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session  # <- tu helper actual (yield AsyncSession)
from app.models import Campaign, IngestedItem
from app.services.search_local import search_local_news  # ✅ usa este nombre

router = APIRouter(prefix="/search-local", tags=["search-local"])

@router.post("/campaign/{campaign_id}")
async def recover_campaign_results(
    campaign_id: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Re-ejecuta la búsqueda local para una campaña que quedó sin resultados
    y persiste los nuevos items en la DB.
    """
    # 1) Obtener campaña
    result = await session.execute(select(Campaign).where(Campaign.id == campaign_id))
    camp: Optional[Campaign] = result.scalars().first()
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # 2) Preparar parámetros (usa lo que ya tengas en Campaign)
    query = camp.query
    city = None
    # city_keywords puede no existir o no ser lista: defensivo
    if hasattr(camp, "city_keywords") and isinstance(camp.city_keywords, list) and camp.city_keywords:
        city = camp.city_keywords[0]

    # 3) Ejecutar búsqueda local (usa tus defaults si faltan)
    items: List[Dict[str, Any]] = await search_local_news(  # ✅ nombre correcto
        query=query,
        city=city or "",
        country=(getattr(camp, "country", None) or "MX"),
        lang=(getattr(camp, "lang", None) or "es-419"),
        days_back=(getattr(camp, "days_back", None) or 14),
        limit=(getattr(camp, "size", None) or 25),
    )

    # 4) Persistir en IngestedItem (evitar duplicados por URL)
    saved = 0
    now = datetime.utcnow()
    for it in items:
        url = (it.get("url") or "").strip()
        title = (it.get("title") or "").strip()
        if not url or not title:
            continue

        dup_check = await session.execute(
            select(IngestedItem).where(
                IngestedItem.campaignId == camp.id,
                IngestedItem.url == url,
            )
        )
        if dup_check.scalars().first():
            continue

        published_at = None
        try:
            raw = it.get("published_at") or it.get("publishedAt")
            if raw:
                published_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            published_at = None

        new_item = IngestedItem(
            campaignId=camp.id,
            sourceId=None,
            title=title,
            url=url,
            publishedAt=published_at,
            status=None,
            createdAt=now,
        )
        session.add(new_item)
        saved += 1

    await session.commit()

    return {
        "campaignId": camp.id,
        "query": camp.query,
        "inserted": saved,
        "found": len(items),
    }


# Endpoint opcional para probar búsquedas sin campaña
from pydantic import BaseModel

class AdHocSearchReq(BaseModel):
    query: str
    city: Optional[str] = ""
    country: Optional[str] = "MX"
    lang: Optional[str] = "es-419"
    days_back: Optional[int] = 14
    limit: Optional[int] = 25

@router.post("")
async def ad_hoc_search(
    body: AdHocSearchReq,
    session: AsyncSession = Depends(get_session),  # lo dejamos por consistencia / futuras persistencias
):
    items = await search_local_news(  # ✅ nombre correcto
        query=body.query,
        city=body.city or "",
        country=body.country or "MX",
        lang=body.lang or "es-419",
        days_back=body.days_back or 14,
        limit=body.limit or 25,
    )
    return {
        "query": body.query,
        "city": body.city or "",
        "country": body.country or "MX",
        "count": len(items),
        "items": items,
    }