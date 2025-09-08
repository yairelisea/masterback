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
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Reejecuta la búsqueda local para una campaña existente y guarda los items en DB.
    Devuelve un resumen con el total insertado/omitido.
    """

    # 1) Cargar campaña con select() (AsyncSession no tiene .query)
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    camp: Optional[Campaign] = result.scalars().first()
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # 2) Preparar parámetros de búsqueda (usa lo que ya guardas en Campaign)
    q = camp.query
    city = None
    if isinstance(camp.city_keywords, list) and camp.city_keywords:
        # si guardas una lista, toma la primera como ciudad principal
        city = camp.city_keywords[0]
    # Defaults razonables
    country = camp.country or "MX"
    lang = camp.lang or "es-419"
    days_back = camp.days_back or 10
    limit = camp.size or 25

    # 3) Ejecutar la búsqueda (tu servicio ya probado con curl)
    data = await perform_local_search(
        query=q,
        city=city or "",       # permite vacío si no tienes ciudad
        country=country,
        lang=lang,
        days_back=days_back,
        limit=limit,
    )

    items: List[Dict[str, Any]] = data.get("items", []) if isinstance(data, dict) else []
    inserted = 0
    skipped = 0

    # 4) Upsert simple de IngestedItem por (campaignId, url)
    for it in items:
        url = (it.get("url") or "").strip()
        title = (it.get("title") or "").strip()
        published_at = it.get("published_at")

        if not url or not title:
            skipped += 1
            continue

        # ¿Existe ya este URL para esta campaña?
        dup_q = select(IngestedItem).where(
            IngestedItem.campaignId == camp.id,
            IngestedItem.url == url,
        )
        dup_res = await db.execute(dup_q)
        exists = dup_res.scalars().first()
        if exists:
            skipped += 1
            continue

        # Parse fecha si viene
        pub_dt = None
        if published_at:
            try:
                pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            except Exception:
                pub_dt = None

        db.add(IngestedItem(
            campaignId=camp.id,
            title=title,
            url=url,
            publishedAt=pub_dt,
        ))
        inserted += 1

    # 5) Commit
    await db.commit()

    return {
        "campaign_id": camp.id,
        "query": q,
        "city": city,
        "country": country,
        "lang": lang,
        "requested": len(items),
        "inserted": inserted,
        "skipped": skipped,
    }