# app/services/news_fetcher.py
import urllib.parse, time, datetime, httpx, feedparser, re
from typing import List, Optional
from dataclasses import dataclass

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

