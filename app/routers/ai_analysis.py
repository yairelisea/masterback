from __future__ import annotations

from fastapi import APIRouter, Query, Header, HTTPException, Depends, Request
from typing import Any, Dict, List, Optional
import urllib.parse
import datetime as dt
import httpx
import xml.etree.ElementTree as ET

# Opcional: si quieres validar userId con auth usa tu get_session/get_current_user
# from ..deps import get_current_user

from ..services.llm import analyze_snippet  # nuestro wrapper de OpenAI

router = APIRouter(prefix="/ai", tags=["ai"])

# ---------------------------
# Util: Google News RSS fetch
# ---------------------------
async def fetch_google_news(
    q: str,
    size: int = 25,
    days_back: int = 14,
    lang: str = "es-419",
    country: str = "MX",
) -> List[Dict[str, Any]]:
    """
    Consulta Google News RSS sin librerías externas.
    Retorna una lista de items: {title, link, pubDate, source}.
    """
    # Google News RSS builder
    # Documentado informalmente: https://news.google.com/rss/search?q=<query>&hl=<lang>&gl=<country>&ceid=<country>:<lang>
    encoded_q = urllib.parse.quote_plus(q)
    base = "https://news.google.com/rss/search"
    params = f"?q={encoded_q}&hl={lang}&gl={country}&ceid={country}:{lang}"
    url = base + params

    items: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url)
        r.raise_for_status()
        xml = r.text

    # Parse XML
    root = ET.fromstring(xml)
    # Los <item> están bajo channel
    for item in root.findall("./channel/item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pubDate = item.findtext("pubDate") or ""
        source = ""
        source_tag = item.find("{http://search.yahoo.com/mrss/}source")
        # A veces también viene como <source> sin namespace
        if source_tag is None:
            s2 = item.find("source")
            if s2 is not None and s2.text:
                source = s2.text.strip()
        else:
            if source_tag.text:
                source = source_tag.text.strip()

        items.append(
            {
                "title": title,
                "link": link,
                "pubDate": pubDate,
                "source": source,
            }
        )

    # Filtro por days_back (si hay pubDate)
    if days_back and days_back > 0:
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=days_back)
        filtered = []
        for it in items:
            try:
                # pubDate formato RFC822, ejemplo: Wed, 03 Sep 2025 19:15:00 GMT
                parsed = dt.datetime.strptime(it["pubDate"], "%a, %d %b %Y %H:%M:%S %Z")
            except Exception:
                # si no podemos parsear, lo dejamos pasar
                parsed = None
            if parsed is None or parsed >= cutoff:
                filtered.append(it)
        items = filtered

    # recorta a size
    return items[: max(1, min(size, 100))]  # limitamos 1..100


# ---------------------------
# Endpoint: /ai/analyze-news
# ---------------------------
@router.get("/analyze-news")
async def analyze_news(
    request: Request,
    q: str = Query(..., description="Consulta (ej. nombre del actor político)"),
    size: int = Query(25, ge=1, le=100),
    days_back: int = Query(14, ge=1, le=60),
    lang: str = Query("es-419"),
    country: str = Query("MX"),
    overall: bool = Query(True, description="Si true, devuelve resumen agregado"),
    userId: Optional[str] = None,  # fallback si el proxy elimina headers
    x_user_id: Optional[str] = Header(default=None),
):
    """
    1) Busca noticias en Google News RSS.
    2) Llama a OpenAI para generar resúmenes y una percepción/sentimiento.
    3) Devuelve: { overall: {...}, items: [...] }
    """
    # Permitir funcionar sin auth estricta (ajústalo si quieres exigir token)
    effective_user = x_user_id or userId or "anonymous"
    # print("AI analyze by user:", effective_user)

    # 1) Buscar noticias
    articles = await fetch_google_news(q=q, size=size, days_back=days_back, lang=lang, country=country)

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

    # 2) Resumir cada nota + percepción rápida con LLM
    summarized_items: List[Dict[str, Any]] = []
    for art in articles:
        title = art.get("title") or ""
        link = art.get("link") or ""
        # Armamos un prompt corto: título + url (no scrapeamos el cuerpo para evitar CORS/capchas)
        # El LLM hará micro-resumen con lo disponible.
        try:
            analysis = await analyze_snippet(
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
                    "llm": analysis,  # {summary, sentiment_label, sentiment_score, topics, stance, perception}
                }
            )
        except Exception as e:
            # Si falla alguna, seguimos con las demás
            summarized_items.append(
                {
                    "title": title,
                    "url": link,
                    "pubDate": art.get("pubDate"),
                    "source": art.get("source"),
                    "llm_error": str(e),
                }
            )

    # 3) Resumen agregado (overall)
    overall_block: Dict[str, Any] = {}
    if overall:
        # Creamos un texto corto con títulos para que LLM haga resumen global
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
        "meta": {"q": q, "size": size, "days_back": days_back, "lang": lang, "country": country},
    }