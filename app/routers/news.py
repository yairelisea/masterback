# app/routers/news.py
from fastapi import APIRouter, Query, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import httpx, urllib.parse, time, datetime
import feedparser

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

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
    """
    Arma el URL de Google News RSS. Usamos comillas para forzar coincidencia exacta.
    """
    q = f"\"{query}\""
    params = {
        "q": q,
        "hl": lang,              # idioma de la interfaz
        "gl": country,           # país
        "ceid": f"{country}:{lang}"
    }
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)

def build_google_news_topic_rss(topic_id: str, lang: str = "es-419", country: str = "MX") -> str:
    """
    Construye URL RSS para un Topic de Google News.
    Ejemplo: https://news.google.com/rss/topics/<topic_id>?hl=es-419&gl=MX&ceid=MX:es-419
    """
    base = f"https://news.google.com/rss/topics/{urllib.parse.quote(topic_id)}"
    params = {"hl": lang, "gl": country, "ceid": f"{country}:{lang}"}
    return base + "?" + urllib.parse.urlencode(params)

def _to_dt(struct_time) -> Optional[datetime.datetime]:
    """
    Convierte struct_time del feed a datetime con tz UTC.
    """
    try:
        if struct_time:
            return datetime.datetime.fromtimestamp(time.mktime(struct_time), tz=datetime.timezone.utc)
    except Exception:
        return None
    return None

def clean_link(url: str) -> str:
    """
    Si el enlace es un redirect de Google News, extrae el destino real (?url=...).
    """
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.endswith("news.google.com"):
            qs = urllib.parse.parse_qs(parsed.query)
            if "url" in qs and qs["url"]:
                return qs["url"][0]
    except Exception:
        pass
    return url

# ---------- Endpoint ----------
@router.get("", response_model=NewsResponse)
async def search_news(
    q: str = Query(..., min_length=2, description="Nombre del actor político o frase exacta"),
    lang: str = Query("es-419"),
    country: str = Query("MX"),
    size: int = Query(35, ge=1, le=100, description="Número de items a devolver"),
    days_back: int = Query(14, ge=1, le=90, description="Rango de días hacia atrás (por fecha de publicación)"),
    campaignId: Optional[str] = Query(None, description="Si lo envías, guarda cada resultado como IngestedItem"),
    session: AsyncSession = Depends(get_session)
):
    """
    Busca en Google News (RSS), filtra por ventana temporal (days_back) y limita a 'size'.
    - Normaliza enlaces de Google News a su URL real.
    - Si 'campaignId' viene, guarda los items como IngestedItem (evitando duplicados por hash del link).
    """
    rss_url = build_google_news_rss(q, lang=lang, country=country)

    # 1) Descargar el RSS
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(rss_url)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Error Google News RSS ({resp.status_code})")

    # 2) Parsear feed
    feed = feedparser.parse(resp.content)
    if feed.bozo:
        raise HTTPException(status_code=502, detail="No se pudo parsear el feed RSS de Google News")

    # 3) Filtrar por fecha
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_back)

    collected: List[NewsItem] = []
    for entry in feed.entries:
        title = getattr(entry, "title", "").strip()
        link = clean_link(getattr(entry, "link", "").strip())
        summary = getattr(entry, "summary", None)

        # Fuente (si viene)
        source = None
        try:
            source = entry.source.title  # type: ignore[attr-defined]
        except Exception:
            pass

        published_at = _to_dt(getattr(entry, "published_parsed", None))

        # Filtrar por ventanas de tiempo
        if published_at and published_at < cutoff:
            continue

        if title and link:
            collected.append(NewsItem(
                title=title,
                link=link,
                source=source,
                published_at=published_at,
                summary=summary
            ))

    # 4) Limitar a 'size'
    items = collected[:size]

    # 5) Guardar en BD (opcional)
    if campaignId and items:
        # Validar que exista la campaña
        cres = await session.execute(select(models.Campaign).where(models.Campaign.id == campaignId))
        if not cres.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="campaignId no existe")

        import hashlib, uuid
        saved = 0
        for it in items:
            # Dedupe por hash de link
            h = hashlib.sha256(it.link.encode()).hexdigest()
            dup = await session.execute(select(models.IngestedItem).where(models.IngestedItem.hash == h))
            if dup.scalar_one_or_none():
                continue

            session.add(models.IngestedItem(
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
            ))
            saved += 1

        if saved:
            await session.commit()

    return NewsResponse(query=q, total=len(items), items=items)


@router.get("/topic", response_model=NewsResponse)
async def search_news_by_topic(
    topic_id: str = Query(..., min_length=8, description="ID del tópico de Google News"),
    lang: str = Query("es-419"),
    country: str = Query("MX"),
    size: int = Query(35, ge=1, le=100),
    days_back: int = Query(30, ge=1, le=120),
    campaignId: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """
    Obtiene notas recientes de un Topic de Google News y (opcionalmente) las persiste en una campaña.
    """
    rss_url = build_google_news_topic_rss(topic_id, lang=lang, country=country)

    # Descargar y parsear RSS
    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.get(rss_url)
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Error Google News Topic RSS ({resp.status_code})")

    feed = feedparser.parse(resp.content)
    if feed.bozo:
        raise HTTPException(status_code=502, detail="No se pudo parsear el feed del Topic")

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_back)

    collected: List[NewsItem] = []
    for entry in feed.entries:
        title = getattr(entry, "title", "").strip()
        link = clean_link(getattr(entry, "link", "").strip())
        summary = getattr(entry, "summary", None)
        source = None
        try:
            source = entry.source.title  # type: ignore[attr-defined]
        except Exception:
            pass
        published_at = _to_dt(getattr(entry, "published_parsed", None))
        if published_at and published_at < cutoff:
            continue
        if title and link:
            collected.append(NewsItem(title=title, link=link, source=source, published_at=published_at, summary=summary))

    items = collected[:size]

    # Persistencia opcional, con dedupe por (campaignId,url) sin usar columnas no existentes
    if campaignId and items:
        cres = await session.execute(select(models.Campaign).where(models.Campaign.id == campaignId))
        if not cres.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="campaignId no existe")
        saved = 0
        now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
        import uuid as _uuid
        for it in items:
            try:
                dup = await session.execute(
                    text('SELECT 1 FROM ingested_items WHERE "campaignId" = :cid AND url = :url LIMIT 1'),
                    {"cid": campaignId, "url": it.link},
                )
                if dup.first():
                    continue
            except Exception:
                pass
            await session.execute(
                text(
                    'INSERT INTO ingested_items (id, "campaignId", title, url, "publishedAt", status, "createdAt")\n'
                    'VALUES (:id, :campaignId, :title, :url, :publishedAt, :status, :createdAt)'
                ),
                {
                    "id": str(_uuid.uuid4()),
                    "campaignId": campaignId,
                    "title": it.title,
                    "url": it.link,
                    "publishedAt": it.published_at,
                    "status": None,
                    "createdAt": now,
                },
            )
            saved += 1
        if saved:
            await session.commit()

    return NewsResponse(query=topic_id, total=len(items), items=items)
