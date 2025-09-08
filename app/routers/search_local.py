# app/routers/search_local.py
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Optional
from app.db import get_db  # tu helper actual
from app.models import Campaign, CampaignItem  # tus modelos
from app.services.search_local import perform_local_search  # tu buscador que ya probaste

router = APIRouter(prefix="/search-local", tags=["search-local"])

@router.post("/campaign/{campaign_id}")
async def recover_campaign_results(campaign_id: str, db: Session = Depends(get_db)):
    camp: Optional[Campaign] = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Toma parámetros desde la campaña (ajusta nombres reales de columnas)
    query = camp.query or camp.name
    city = getattr(camp, "city", None)
    country = getattr(camp, "country", "MX")
    lang = getattr(camp, "lang", "es-419")
    days_back = getattr(camp, "days_back", 10)
    limit = getattr(camp, "limit", 25)

    # Ejecuta búsqueda local (lo que ya comprobaste por curl)
    results = await perform_local_search(
        query=query,
        city=city,
        country=country,
        lang=lang,
        days_back=days_back,
        limit=limit,
    )
    items = results.get("items", [])

    # Persiste (evita duplicados por url/hash)
    saved = 0
    for it in items:
        url = it.get("url")
        if not url:
            continue
        exists = (
            db.query(CampaignItem)
            .filter(CampaignItem.campaign_id == campaign_id, CampaignItem.url == url)
            .first()
        )
        if exists:
            continue
        db.add(CampaignItem(
            campaign_id=campaign_id,
            title=it.get("title"),
            url=url,
            source=it.get("source"),
            published_at=it.get("published_at"),
            summary=it.get("summary"),
        ))
        saved += 1

    db.commit()

    return {
        "campaign_id": campaign_id,
        "saved_count": saved,
        "total_found": len(items),
    }