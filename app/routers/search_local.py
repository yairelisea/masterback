# app/routers/search_local.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.search_local import search_local_news

# Si quieres persistir, importa tu helper de DB
# from app.db import save_articles  # <-- ajústalo a tu proyecto si existe

router = APIRouter(prefix="/search-local", tags=["search-local"])

class SearchLocalBody(BaseModel):
    query: str = Field(..., description="Texto a buscar (actor/localidad)")
    city: Optional[str] = None
    country: Optional[str] = None
    lang: Optional[str] = "es-419"
    days_back: int = 7
    limit: int = 25
    # campaign_id es opcional; si lo recibimos, guardamos con ese id
    campaign_id: Optional[str] = None

@router.post("", summary="Busca noticias locales (RSS públicos) y retorna items normalizados")
async def search_local(body: SearchLocalBody) -> Dict[str, Any]:
    try:
        items = await search_local_news(
            query=body.query,
            city=body.city,
            country=body.country,
            lang=body.lang,
            days_back=body.days_back,
            limit=body.limit,
        )

        # Persistencia opcional si traes campaign_id y tienes helper
        # if body.campaign_id and items:
        #     try:
        #         save_articles(campaign_id=body.campaign_id, items=items)
        #     except Exception:
        #         pass  # no rompemos la respuesta si falla guardar

        return {
            "query": body.query,
            "city": body.city,
            "country": body.country,
            "count": len(items),
            "items": items,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"search_local failed: {e}")