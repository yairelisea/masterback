# app/routers/search_local.py
from __future__ import annotations
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from sqlalchemy.orm import Session
from app.db.session import get_db  # ajusta al helper que ya usas

from app.services.search_local import run_local_search_and_store

router = APIRouter(prefix="/search", tags=["search"])

class SearchLocalBody(BaseModel):
    q: str = Field(..., description="Consulta o nombre del actor local")
    country: str = "MX"
    lang: str = "es-419"
    size: int = 25
    campaign_id: Optional[str] = None
    sources: Optional[List[str]] = None  # ej. ["google_news","web_generic","local_publishers"]

@router.post("/local")
async def search_local(body: SearchLocalBody, db: Session = Depends(get_db)):
    try:
        result = await run_local_search_and_store(
            db,
            body.q,
            country=body.country,
            lang=body.lang,
            size=body.size,
            campaign_id=body.campaign_id,
            sources=body.sources,
        )
        return {"ok": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"local-search failed: {e}")