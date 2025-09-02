# app/routers/news.py
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import httpx, urllib.parse, time, datetime
import feedparser

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..db import get_session
from .. import models

router = APIRouter(prefix="/news", tags=["news"])

# ---------- Schemas ----------
class NewsItem(BaseModel):
    title: str
    link: str
    source: Optional[str] = None
    published_at: Optional[datetime.datetime] = None
    summary: Optional[str] = None

class NewsResponse(BaseModel):
    query: str
    total: int
    items: List[NewsItem]

# ---------- Helpers ----------
def build_google_news_rss(query: str, lang: str = "es-419", country: str = "MX") -> str:
    # comillas para búsquedas exactas ayudan con actores políticos
    q = f"\"{query}\""
    params = {
        "q": q,
        "hl": lang,   # idioma UI
        "gl": country, # país
        "ceid": f"{country}:{lang}"
    }
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)

def _to_dt(struct_time) -> Optional[datetime.datetime]:
    try:
        if struct_time:
            return datetime.datetime.fromtimestamp(time.mktime(struct_time), tz=datetime.timezone.utc)
    except Exception:
        return None
    return None

# ---------- Endpoints ----------
@router.get("", response_model=NewsResponse)
async def search_news(
    q: str = Query(..., min_length=2, description="Nombre del actor político o frase exacta"),
    lang: str = Query("es-419"),
    country: str = Query("MX"),
    limit: int = Query(15, ge=1, le=50, description="Máximo de items a devolver"),
    campaignId: Optional[str] = Query(None, description="Si lo envías, guarda cada resultado como IngestedItem"),
    session: AsyncSession = Depends(get_session)
):
    """
    Busca en Google News (RSS) y devuelve lista de notas.
    Si `campaignId` viene, intenta guardar cada item en la base (evitando duplicados por hash del link).
    """
    rss_url = build_google_news_rss(q, lang=lang, country=country)

    # Descarga el RSS con timeout
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(rss_url)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Error al consultar Google News RSS ({resp.status_code})")

    feed = feedparser.parse(resp.content)
    if feed.bozo:
        # feed.bozo señala parse errors
        raise HTTPException(status_code=502, detail="No se pudo parsear el feed RSS de Google News")

    items: List[NewsItem] = []
    for entry in feed.entries[:limit]:
        title = getattr(entry, "title", "").strip()
        link = getattr(entry, "link", "").strip()
        summary = getattr(entry, "summary", None)
        # El "source" suele venir en entry.source.title si está presente
        source = None
        try:
            source = entry.source.title  # type: ignore
        except Exception:
            pass
        published_at = _to_dt(getattr(entry, "published_parsed", None))

        items.append(NewsItem(
            title=title,
            link=link,
            source=source,
            published_at=published_at,
            summary=summary
        ))

    # Guardar (opcional) en BD como IngestedItem
    if campaignId and items:
        # Validar que exista la campaña
        cres = await session.execute(select(models.Campaign).where(models.Campaign.id == campaignId))
        campaign = cres.scalar_one_or_none()
        if not campaign:
            raise HTTPException(status_code=404, detail="campaignId no existe")

        import hashlib, uuid
        saved = 0
        for it in items:
            if not it.link:
                continue
            h = hashlib.sha256(it.link.encode()).hexdigest()

            # evitar duplicados por hash
            dup = await session.execute(
                select(models.IngestedItem).where(models.IngestedItem.hash == h)
            )
            if dup.scalar_one_or_none():
                continue

            row = models.IngestedItem(
                id=str(uuid.uuid4()),
                campaignId=campaignId,
                sourceType=models.SourceType.NEWS,
                sourceUrl=it.link,
                contentUrl=it.link,
                author=None,
                title=it.title,
                excerpt=(it.summary or None),
                publishedAt=it.published_at,
                status=models.ItemStatus.QUEUED,
                hash=h
            )
            session.add(row)
            saved += 1

        if saved:
            await session.commit()

    return NewsResponse(query=q, total=len(items), items=items)