# app/routers/search_local.py
from __future__ import annotations

from typing import Optional, List, Dict, Any, Union
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session  # <- tu helper actual (yield AsyncSession)
from app.models import Campaign, IngestedItem, ItemStatus
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
    city: Optional[str] = None
    # city_keywords puede no existir o no ser lista: defensivo
    if hasattr(camp, "city_keywords") and isinstance(camp.city_keywords, list) and camp.city_keywords:
        try:
            # Une todas las palabras clave por compatibilidad con front (no solo la primera)
            city = " ".join([str(x) for x in camp.city_keywords if isinstance(x, (str, int, float))]).strip() or None
        except Exception:
            city = str(camp.city_keywords[0])

    # 3) Ejecutar búsqueda local (usa tus defaults si faltan)
    try:
        items: List[Dict[str, Any]] = await search_local_news(  # ✅ nombre correcto
            query=query,
            city=city or "",
            country=(getattr(camp, "country", None) or "MX"),
            lang=(getattr(camp, "lang", None) or "es-419"),
            days_back=(getattr(camp, "days_back", None) or 14),
            limit=(getattr(camp, "size", None) or 25),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"local search failed: {e}")

    # 4) Persistir en IngestedItem (evitar duplicados por URL)
    saved = 0
    errors: List[str] = []
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

        try:
            new_item = IngestedItem(
                campaignId=camp.id,
                sourceId=None,
                title=title,
                url=url,
                publishedAt=published_at,
                status=ItemStatus.PENDING,
                createdAt=now,
            )
            session.add(new_item)
            saved += 1
        except Exception as e:
            errors.append(str(e))

    try:
        await session.commit()
    except Exception as e:
        # best-effort rollback; report error
        try:
            await session.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"db commit failed: {e}")

    return {
        "campaignId": camp.id,
        "query": camp.query,
        "inserted": saved,
        "found": len(items),
        "errors": errors,
    }


# Endpoint opcional para probar búsquedas sin campaña
from pydantic import BaseModel, Field

# --- Ad-hoc search (sin campaña) ---
# Permite probar la búsqueda local sin tocar DB.
class AdHocSearchReq(BaseModel):
    query: str
    # Acepta string o lista de strings (compat con front que manda arrays)
    city: Optional[Union[str, List[str]]] = None
    city_keywords: Optional[List[str]] = None
    country: Optional[str] = "MX"
    lang: Optional[str] = "es-419"
    days_back: int = Field(default=14, ge=1, le=60, description="Rango típico 1..60 días")
    limit: int = Field(default=25, ge=1, le=50, description="Máximo 50 para evitar abuso")

@router.post("", summary="Ad-hoc local search", tags=["search-local"])
async def ad_hoc_search(
    body: AdHocSearchReq,
    session: AsyncSession = Depends(get_session),  # se mantiene por consistencia
):
    """
    Ejecuta la búsqueda local sin asociarla a una campaña de la base de datos.
    Útil para validación rápida desde el front o curl.
    """
    try:
        # Coerción de city para compatibilidad: string o lista
        city_val: Optional[str] = None
        if isinstance(body.city, list) and body.city:
            city_val = " ".join([str(x) for x in body.city if isinstance(x, (str, int, float))])
        elif isinstance(body.city, str):
            city_val = body.city
        elif body.city_keywords:
            city_val = " ".join([str(x) for x in body.city_keywords if isinstance(x, (str, int, float))])

        items = await search_local_news(
            query=body.query,
            city=(city_val or ""),
            country=body.country or "MX",
            lang=body.lang or "es-419",
            days_back=body.days_back,
            limit=body.limit,
        )
        return {
            "query": body.query,
            "city": body.city or "",
            "country": body.country or "MX",
            "count": len(items),
            "items": items or [],
        }
    except HTTPException:
        raise
    except Exception as e:
        # Nunca exponemos traceback al cliente
        raise HTTPException(status_code=500, detail=f"ad_hoc_search failed: {e}")
