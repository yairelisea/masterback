# app/services/news_fetcher.py
from __future__ import annotations
import urllib.parse, time, datetime, httpx, feedparser, re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from .query_expand import expand_actor
from .rank import score_item

def build_google_news_rss(query: str, lang: str = "es-419", country: str = "MX") -> str:
    q = f"\"{query}\""
    params = {"q": q, "hl": lang, "gl": country, "ceid": f"{country}:{lang}"}
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)

def _to_dt(struct_time) -> Optional[datetime.datetime]:
    try:
        if struct_time:
            return datetime.datetime.fromtimestamp(time.mktime(struct_time), tz=datetime.timezone.utc)
    except Exception:
        return None
    return None

def clean_link(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.netloc.endswith("news.google.com"):
            qs = urllib.parse.parse_qs(parsed.query)
            if "url" in qs and qs["url"]:
                return qs["url"][0]
    except Exception:
        pass
    return url

@dataclass
class FetchedItem:
    title: str
    link: str
    source: Optional[str]
    published_at: Optional[datetime.datetime]
    summary: Optional[str]

async def fetch_news(
    q: str,
    *,
    size: int = 35,
    days_back: int = 14,
    lang: str = "es-419",
    country: str = "MX",
    city_keywords: Optional[List[str]] = None
) -> List[FetchedItem]:
    """
    Trae noticias de Google News RSS para 'q', filtra por ventana de tiempo
    y (opcional) por palabras clave de ciudad/localidad.
    """
    rss_url = build_google_news_rss(q, lang=lang, country=country)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(rss_url)
        resp.raise_for_status()

    feed = feedparser.parse(resp.content)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_back)

    # Prepara regex OR para city_keywords (case-insensitive)
    ck_re = None
    if city_keywords:
        escaped = [re.escape(s.strip()) for s in city_keywords if s and s.strip()]
        if escaped:
            ck_re = re.compile(r"(" + "|".join(escaped) + r")", re.IGNORECASE)

    items: List[FetchedItem] = []
    for e in feed.entries:
        dt = _to_dt(getattr(e, "published_parsed", None))
        if dt and dt < cutoff:
            continue
        title = getattr(e, "title", "").strip()
        link = clean_link(getattr(e, "link", "").strip())
        summary = getattr(e, "summary", "") or ""
        source = None
        try:
            source = e.source.title  # type: ignore
        except Exception:
            pass
        if not (title and link):
            continue

        # Marcamos city_hit de forma suave (no filtramos):
        city_hit = 0
        if ck_re:
            blob = f"{title}\n{summary}\n{link}"
            if ck_re.search(blob) is not None:
                city_hit = 1

        # Guardamos también city_hit como metadato blando (si tu struct lo admite)
        try:
            items.append(FetchedItem(title=title, link=link, source=source, published_at=dt, summary=summary, city_hit=city_hit))
        except TypeError:
            items.append(FetchedItem(title=title, link=link, source=source, published_at=dt, summary=summary))
        if len(items) >= size:
            break
    return items


# New relaxed multi-query search helpers
async def _gn_fetch(queries: List[str], days_back: int, lang: str, country: str) -> List[Dict[str, Any]]:
    """
    Ejecuta fetch_news para cada query y devuelve lista de dicts
    compatibles con el pipeline: {title, url, summary, published_at, source}.
    """
    out: List[Dict[str, Any]] = []
    for q in queries:
        try:
            items = await fetch_news(
                q,
                size=35,
                days_back=days_back,
                lang=lang,
                country=country,
                city_keywords=None,
            )
            for it in items:
                out.append({
                    "title": it.title,
                    "url": it.link,
                    "summary": it.summary,
                    "published_at": it.published_at,
                    "source": it.source,
                })
        except Exception:
            continue
    return out


async def _site_backfill(aliases: List[str], city_boost: List[str], days_back: int, lang: str, country: str) -> List[Dict[str, Any]]:
    # Optional: hit specific local outlets with `site:` queries. Can return empty list safely.
    return []


def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set(); out = []
    for it in items:
        u = (it.get("url") or "").strip().lower()
        if u and u not in seen:
            seen.add(u); out.append(it)
    return out


async def search_google_news_multi_relaxed(
    q: str,
    size: int = 25,
    days_back: int = 14,
    lang: str = "es-419",
    country: str = "MX",
    city_keywords: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Relaxed recall strategy to guarantee up to `size` items:
    1) aliases + city boost
    2) aliases national (no city)
    3) optional site backfill
    Then dedupe, soft-rank (actor prioritized), and truncate.
    """
    aliases = expand_actor(q, extra_aliases=None)
    city_boost = [c for c in (city_keywords or []) if c and c.strip()]

    # Build boosted queries
    queries_p1 = []
    for a in aliases:
        if city_boost:
            or_cities = " OR ".join([f'"{c}"' for c in city_boost])
            queries_p1.append(f'"{a}" ({or_cities})')
        else:
            queries_p1.append(f'"{a}"')

    items: List[Dict[str, Any]] = []

    # Pass 1: GN with city boost
    try:
        items += await _gn_fetch(queries_p1, days_back, lang, country)
    except Exception:
        pass

    # Pass 2: GN without city (national)
    if len(items) < size:
        try:
            queries_p2 = [f'"{a}"' for a in aliases]
            items += await _gn_fetch(queries_p2, days_back, lang, country)
        except Exception:
            pass

    # Pass 3: site backfill (optional)
    if len(items) < size:
        try:
            items += await _site_backfill(aliases, city_boost, days_back, lang, country)
        except Exception:
            pass

    # Dedupe
    items = _dedupe(items)

    # Soft ranking
    scored = [(score_item(it, aliases, city_boost), it) for it in items]
    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [it for _, it in scored]

    return ranked[:size]
