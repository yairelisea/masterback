
from __future__ import annotations
from typing import List, Dict, Any, Optional
import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from ..db import SessionLocal
from ..models import Campaign, IngestedItem, ItemStatus
from .query_builder import build_query_variants
from .search_local import search_local_news
from .news_fetcher import search_google_news_multi_relaxed
from .query_builder import build_basic_query
import urllib.parse, feedparser, re, datetime as _dt, time as _time

async def _google_news_fetch(q: str, lang: str, country: str, since: _dt.datetime, limit: int):
    """Minimal GN via RSS using feedparser (sync)."""
    q_param = f'"{q}"'
    params = {"q": q_param, "hl": lang or "es-419", "gl": country or "MX", "ceid": f"{(country or 'MX')}:{(lang or 'es-419')}"}
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    feed = feedparser.parse(url)
    out = []
    for e in getattr(feed, "entries", [])[: max(50, limit)]:
        title = getattr(e, "title", "") or ""
        link = getattr(e, "link", "") or ""
        if not (title and link):
            continue
        dt = None
        try:
            if getattr(e, "published_parsed", None):
                dt = _dt.datetime.fromtimestamp(_time.mktime(e.published_parsed), tz=_dt.timezone.utc)
        except Exception:
            dt = None
        if since and dt and dt < since:
            continue
        out.append({"title": title, "url": link, "publishedAt": dt})
        if len(out) >= limit:
            break
    return out


async def _bing_news_fetch(q: str, since: _dt.datetime, limit: int) -> List[Dict[str, Any]]:
    """Minimal Bing News via RSS using feedparser (sync)."""
    base = "https://www.bing.com/news/search"
    params = {"q": q, "format": "rss"}
    url = base + "?" + urllib.parse.urlencode(params)
    feed = feedparser.parse(url)
    out: List[Dict[str, Any]] = []
    for e in getattr(feed, "entries", [])[: max(50, limit)]:
        title = getattr(e, "title", "") or ""
        link = getattr(e, "link", "") or ""
        if not (title and link):
            continue
        dt = None
        try:
            if getattr(e, "published_parsed", None):
                dt = _dt.datetime.fromtimestamp(_time.mktime(e.published_parsed), tz=_dt.timezone.utc)
        except Exception:
            dt = None
        if since and dt and dt < since:
            continue
        out.append({"title": title, "url": link, "publishedAt": dt})
        if len(out) >= limit:
            break
    return out


async def _safe_search_google(q: str, lang: str, country: str, since: datetime, size: int) -> List[Dict[str, Any]]:
    try:
        items = await _google_news_fetch(q=q, lang=lang, country=country, since=since, limit=size)
        return items or []
    except Exception:
        return []

async def _safe_search_bing(q: str, since: datetime, size: int) -> List[Dict[str, Any]]:
    try:
        items = await _bing_news_fetch(q=q, since=since, limit=size)
        return items or []
    except Exception:
        return []

async def _safe_search_local(q: str, city_keywords: Optional[list[str]], lang: str, country: str, since: datetime, size: int) -> List[Dict[str, Any]]:
    try:
        # Coerce list of city keywords into a single hint string
        city = None
        if city_keywords:
            try:
                city = " ".join([str(x) for x in city_keywords if isinstance(x, (str, int, float))])
            except Exception:
                city = str(city_keywords[0])
        days_back = max(1, int((datetime.utcnow() - since).days or 1))
        items = await search_local_news(
            query=q,
            city=city or "",
            country=country,
            lang=lang,
            days_back=days_back,
            limit=size,
        )
        # Map to expected keys for downstream
        out: List[Dict[str, Any]] = []
        for it in items:
            out.append({
                "title": it.get("title"),
                "url": it.get("url"),
                "publishedAt": it.get("published_at") or it.get("publishedAt"),
            })
        return out
    except Exception:
        return []

def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for it in items:
        url = (it.get("url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            out.append(it)
    return out

async def kickoff_campaign_ingest(campaign_id: str) -> None:
    """Run GN + Local search and persist IngestedItem rows for the given campaign."""
    async with SessionLocal() as db:  # type: AsyncSession
        campaign = await db.get(Campaign, campaign_id)
        if not campaign:
            return
        
        q = campaign.query
        lang = campaign.lang or "es-419"
        country = campaign.country or "MX"
        size = campaign.size or 25
        # Pausamos búsqueda local y fijamos ventana a 30 días (1 mes)
        days_back = 30
        city_keywords = campaign.city_keywords or None
        since = datetime.utcnow() - timedelta(days=days_back)
        
        all_items: List[Dict[str, Any]] = []

        # Consulta básica: "actor" + rol inferido + ciudad
        basic_q = build_basic_query(actor=q, campaign_name=campaign.name, city_keywords=city_keywords)
        if basic_q:
            gn = await _safe_search_google(basic_q, lang, country, since, size)
            all_items.extend(gn)
            # También prova Bing con la misma consulta básica
            bn = await _safe_search_bing(basic_q, since, size)
            all_items.extend(bn)

        # Sin fallback: solo lo que haya en el mes (GN+Bing)
        
        # normalize to expected keys
        normed = []
        for it in all_items:
            title = (it.get("title") or "").strip()
            url = (it.get("url") or "").strip()
            pub = it.get("publishedAt")
            if not url or not title:
                continue
            normed.append({
                "title": title[:512],
                "url": url,
                "publishedAt": pub
            })
        
        # No intentamos llegar a una cuota: limitamos a 'size' y listo
        normed = _dedupe(normed)[: size]
        
        for it in normed:
            await db.execute(
                text(
                    'INSERT INTO ingested_items (id, "campaignId", title, url, "publishedAt", status, "createdAt")\n'
                    'VALUES (:id, :campaignId, :title, :url, :publishedAt, :status, :createdAt)'
                ),
                {
                    "id": str(uuid.uuid4()),
                    "campaignId": campaign.id,
                    "title": it["title"],
                    "url": it["url"],
                    "publishedAt": it.get("publishedAt"),
                    "status": None,  # NULL = pendiente
                    "createdAt": datetime.utcnow(),
                },
            )
        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            raise
