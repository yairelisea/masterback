# app/routers/search_local.py
from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session  # <- tu helper actual (yield AsyncSession)
from app.models import Campaign, IngestedItem
from app.services.search_local import search_local_news  # tu buscador ya probado

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
    result = await session.execute(
        select(Campaign).where(Campaign.id == campaign_id)
    )
    camp: Optional[Campaign] = result.scalars().first()
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # 2) Preparar parámetros (usa lo que ya tengas en Campaign)
    query = camp.query
    # Si guardas ciudad en city_keywords (array), puedes tomar la primera
    city = None
    if isinstance(camp.city_keywords, list) and camp.city_keywords:
        city = camp.city_keywords[0]

    # 3) Ejecutar búsqueda local (usa tus defaults si faltan)
    search_resp: Dict[str, Any] = await perform_local_search(
        query=query,
        city=city or "",
        country=camp.country or "MX",
        lang=camp.lang or "es-419",
        days_back=camp.days_back or 14,
        limit=camp.size or 25,
    )

    items: List[Dict[str, Any]] = search_resp.get("items") or []

    # 4) Persistir en IngestedItem (evitar duplicados por URL)
    saved = 0
    now = datetime.utcnow()
    for it in items:
        url = (it.get("url") or "").strip()
        title = (it.get("title") or "").strip()
        if not url or not title:
            continue

        # ¿existe ya un item con misma URL y campaña?
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
            # si viene ISO: "2025-08-30T07:00:00+00:00"
            raw = it.get("published_at") or it.get("publishedAt")
            if raw:
                published_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            published_at = None

        new_item = IngestedItem(
            campaignId=camp.id,
            sourceId=None,  # si luego ligas a SourceLink, complétalo
            title=title,
            url=url,
            publishedAt=published_at,
            status=None,  # usa tu Enum si lo deseas (PENDING, etc.)
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
    session: AsyncSession = Depends(get_session),  # dejado por consistencia / futuras persistencias
):
    resp = await perform_local_search(
        query=body.query,
        city=body.city or "",
        country=body.country or "MX",
        lang=body.lang or "es-419",
        days_back=body.days_back or 14,
        limit=body.limit or 25,
    )
    return resp