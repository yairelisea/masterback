from __future__ import annotations

from fastapi import APIRouter, Query, Header, HTTPException, Request
from typing import Any, Dict, List, Optional
import urllib.parse
import datetime as dt
import httpx
import os
import xml.etree.ElementTree as ET

from ..services.llm import analyze_snippet  # wrapper hacia OpenAI (ya existente)

router = APIRouter(prefix="/ai", tags=["ai"])

# -----------------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------------

def _parse_pubdate(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    # Ej: "Wed, 03 Sep 2025 19:15:00 GMT"
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return dt.datetime.strptime(s, fmt)
        except Exception:
            pass
    return None

def _extract_source(item: ET.Element) -> str:
    """
    Google News RSS trae <source url="...">Nombre</source>.
    A veces aparece con distintos namespaces o sin ellos.
    Buscamos de forma tolerante.
    """
    # 1) sin namespace
    s = item.find("source")
    if s is not None and (s.text or "").strip():
        return s.text.strip()

    # 2) namespace común de Google News
    for ns in [
        "http://news.google.com",    # frecuente
        "http://www.google.com",     # variantes
        "http://search.yahoo.com/mrss/",  # por si acaso (media RSS)
    ]:
        tag = item.find(f"{{{ns}}}source")
        if tag is not None and (tag.text or "").strip():
            return tag.text.strip()

    return ""

def _extract_link(item: ET.Element) -> str:
    """
    El <link> de Google News muchas veces apunta a un redirect propio.
    Aquí devolvemos el texto tal cual; (opcional) podrías resolver el redirect
    si lo necesitas (HEAD/GET follow_redirects=True).
    """
    link = item.findtext("link") or ""
    return link.strip()

# -----------------------------------------------------------------------------------
# Google News RSS
# -----------------------------------------------------------------------------------

async def fetch_google_news(
    q: str,
    size: int = 25,
    days_back: int = 14,
    lang: str = "es-419",
    country: str = "MX",
) -> List[Dict[str, Any]]:
    """
    Consulta el RSS de Google News.
    Retorna items: {title, link, pubDate, source}
    """
    encoded_q = urllib.parse.quote_plus(q)
    base = "https://news.google.com/rss/search"
    params = f"?q={encoded_q}&hl={lang}&gl={country}&ceid={country}:{lang}"
    url = base + params

    items: List[Dict[str, Any]] = []

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; BBXBot/1.0; +https://blackboxmonitor.com)"
    }
    async with httpx.AsyncClient(timeout=7, headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        xml = r.text

    root = ET.fromstring(xml)

    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = _extract_link(item)
        pubDate = (item.findtext("pubDate") or "").strip()
        source = _extract_source(item)

        items.append(
            {
                "title": title,
                "link": link,
                "pubDate": pubDate,
                "source": source,
            }
        )

    # filtro por rango temporal
    if days_back and days_back > 0:
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=days_back)
        filtered: List[Dict[str, Any]] = []
        for it in items:
            parsed = _parse_pubdate(it.get("pubDate"))
            if parsed is None or parsed >= cutoff:
                filtered.append(it)
        items = filtered

    # recorte de tamaño
    size = max(1, min(size, 100))
    return items[:size]

# -----------------------------------------------------------------------------------
# Endpoint principal
# -----------------------------------------------------------------------------------

@router.get("/analyze-news")
async def analyze_news(
    request: Request,
    q: str = Query(..., description="Consulta (ej. nombre del actor político)"),
    size: int = Query(25, ge=1, le=100),
    days_back: int = Query(14, ge=1, le=60),
    lang: str = Query("es-419"),
    country: str = Query("MX"),
    overall: bool = Query(True, description="Si true, devuelve resumen agregado"),
    # Fallbacks por si algún proxy quita headers:
    userId: Optional[str] = None,
    x_user_id: Optional[str] = Header(default=None),
):
    """
    1) Busca titulares en Google News (RSS).
    2) Pide al LLM micro-resumen + sentimiento por titular.
    3) (Opcional) Resumen agregado (“overall”).
    """
    effective_user = x_user_id or userId or "anonymous"

    # 1) fuentes
    try:
        articles = await fetch_google_news(
            q=q, size=size, days_back=days_back, lang=lang, country=country
        )
    except Exception as e:
        # problemas de red, XML, etc.
        raise HTTPException(status_code=502, detail=f"RSS fetch error: {e}")

    if not articles:
        return {
            "overall": {
                "summary": "No se encontraron notas en el periodo solicitado.",
                "sentiment_label": None,
                "sentiment_score": None,
                "topics": [],
                "perception": {},
            },
            "items": [],
            "meta": {"q": q, "size": size, "days_back": days_back, "lang": lang, "country": country},
        }

    # 2) análisis por ítem
    summarized_items: List[Dict[str, Any]] = []
    # Para evitar timeouts si hay clave real de OpenAI, limitamos el nº de análisis por item
    MAX_ANALYZED = int(os.getenv("AI_PER_ITEM_LIMIT", "12"))
    to_process = articles[: max(1, min(len(articles), MAX_ANALYZED))]
    for art in to_process:
        title = art.get("title") or ""
        link = art.get("link") or ""
        try:
            llm = await analyze_snippet(
                title=title.strip(),
                summary=f"Enlace: {link}",
                actor=q,
            )
            summarized_items.append(
                {
                    "title": title,
                    "url": link,
                    "pubDate": art.get("pubDate"),
                    "source": art.get("source"),
                    "llm": llm,  # {summary, sentiment_label, sentiment_score, topics, stance, perception}
                }
            )
        except Exception as e:
            summarized_items.append(
                {
                    "title": title,
                    "url": link,
                    "pubDate": art.get("pubDate"),
                    "source": art.get("source"),
                    "llm_error": str(e),
                }
            )

    # 3) resumen agregado
    overall_block: Dict[str, Any] = {}
    if overall:
        joined = "\n".join(f"- {it['title']}" for it in summarized_items if it.get("title"))
        try:
            agg = await analyze_snippet(
                title=f"Resumen global de cobertura sobre: {q}",
                summary=f"Titulares recientes:\n{joined}",
                actor=q,
            )
            overall_block = {
                "summary": agg.get("summary"),
                "sentiment_label": agg.get("sentiment_label"),
                "sentiment_score": agg.get("sentiment_score"),
                "topics": agg.get("topics") or [],
                "perception": agg.get("perception") or {},
            }
        except Exception as e:
            overall_block = {
                "summary": f"No fue posible generar el resumen agregado: {e}",
                "sentiment_label": None,
                "sentiment_score": None,
                "topics": [],
                "perception": {},
            }

    return {
        "overall": overall_block,
        "items": summarized_items,
        "meta": {
            "q": q, "size": size, "days_back": days_back, "lang": lang, "country": country,
            "user": effective_user,
        },
    }
