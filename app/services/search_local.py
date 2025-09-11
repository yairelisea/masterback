# app/services/search_local.py
from __future__ import annotations

import asyncio
import datetime as dt
import re
from typing import Any, Dict, List, Optional, Tuple
import feedparser
import httpx
import os
import hashlib

# Opcional: usar OpenAI para re-ranqueo (si tienes OPENAI_API_KEY)
USE_OPENAI = bool(os.getenv("OPENAI_API_KEY"))
if USE_OPENAI:
    try:
        from openai import OpenAI
        _client = OpenAI()
    except Exception:
        USE_OPENAI = False
        _client = None  # type: ignore

# -------- Utils --------

def _now_utc() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)

def _parse_dt(value: Any) -> Optional[dt.datetime]:
    # feedparser ya entrega .published_parsed en time.struct_time
    try:
        if hasattr(value, "tm_year"):
            return dt.datetime(*value[:6], tzinfo=dt.timezone.utc)
    except Exception:
        pass
    return None

def _domain_from_link(link: str) -> str:
    m = re.search(r"https?://([^/]+)/?", link, re.I)
    return m.group(1).lower() if m else ""

def _hash_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()

# -------- RSS providers (sin costo) --------

def _google_news_rss(query: str, country: Optional[str] = None, lang: Optional[str] = None) -> str:
    # hl=idioma, gl=país, ceid=PAIS:IDIOMA
    # Google News acepta ceid=MX:es-419 por ejemplo.
    q = re.sub(r"\s+", "+", query.strip())
    hl = (lang or "es-419")
    gl = (country or "MX")
    ceid = f"{gl}:{hl}"
    return f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"

def _bing_news_rss(query: str) -> str:
    q = re.sub(r"\s+", "+", query.strip())
    return f"https://www.bing.com/news/search?q={q}&format=rss"

def _rss_sources(query: str, city: Optional[str], country: Optional[str], lang: Optional[str]) -> List[str]:
    q_full = query if not city else f"{query} {city}"
    return [
        _google_news_rss(q_full, country=country, lang=lang),
        _bing_news_rss(q_full),
        # Puedes añadir otras fuentes RSS abiertas si gustas
    ]

# -------- Fetch & normalize --------

async def _fetch_rss(url: str, timeout: int = 7) -> feedparser.FeedParserDict:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers={"User-Agent": "BBX/1.0"})
        r.raise_for_status()
        # feedparser puede recibir bytes
        return feedparser.parse(r.content)

def _normalize_entry(entry) -> Optional[Dict[str, Any]]:
    link = (entry.get("link") or "").strip()
    title = (entry.get("title") or "").strip()
    if not link or not title:
        return None
    published = _parse_dt(entry.get("published_parsed")) or _parse_dt(entry.get("updated_parsed"))
    source = _domain_from_link(link)
    summary = (entry.get("summary") or "").strip()
    return {
        "id": _hash_id(link),
        "title": title,
        "url": link,
        "source": source,
        "published_at": published.isoformat() if published else None,
        "summary": summary,
    }

def _within_days(published_iso: Optional[str], days_back: int) -> bool:
    if not published_iso:
        return True  # si no hay fecha, no descartamos
    try:
        d = dt.datetime.fromisoformat(published_iso)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return True
    return (_now_utc() - d) <= dt.timedelta(days=days_back)

def _score_city_hit(title: str, summary: str, city: Optional[str]) -> int:
    if not city:
        return 0
    c = city.strip().lower()
    txt = f"{title} {summary}".lower()
    return 1 if c in txt else 0

# -------- Optional: OpenAI re-rank --------

def _rerank_with_openai(items: List[Dict[str, Any]], query: str, city: Optional[str], top_k: int) -> List[Dict[str, Any]]:
    if not USE_OPENAI or not items:
        return items[:top_k]
    try:
        # Construimos un prompt compacto para ranking
        lines = []
        for i, it in enumerate(items[:50], 1):
            lines.append(f"{i}. {it['title']} — {it.get('source','')} — {it.get('url','')}")
        question = f"Rank the following news for relevance to: '{query}' in city '{city or 'N/A'}'. Return top {top_k} indices only as a comma-separated list."

        prompt = question + "\n\n" + "\n".join(lines)

        resp = _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=120,
        )
        text = resp.choices[0].message.content.strip()
        # Parsear "1,4,2"
        idxs = []
        for tok in re.split(r"[,\s]+", text):
            try:
                n = int(tok)
                if 1 <= n <= len(items):
                    idxs.append(n-1)
            except Exception:
                pass
        seen = set()
        ranked = []
        for i in idxs:
            if i not in seen:
                ranked.append(items[i])
                seen.add(i)
        # Completar si faltan
        for i, it in enumerate(items):
            if i not in seen and len(ranked) < top_k:
                ranked.append(it)
        return ranked[:top_k]
    except Exception:
        return items[:top_k]

# -------- Public API del servicio --------

async def search_local_news(
    query: str,
    city: Optional[str] = None,
    country: Optional[str] = None,
    lang: Optional[str] = None,
    days_back: int = 7,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """
    Busca en RSS (Google/Bing), filtra por days_back y (si hay) city mention,
    normaliza resultados y (opcional) re-ranquea con OpenAI.
    """
    urls = _rss_sources(query, city, country, lang)
    collected: List[Dict[str, Any]] = []
    seen_ids = set()

    # Fetch feeds concurrently to keep latency low (<= ~7s)
    feeds: List[feedparser.FeedParserDict] = []
    results = await asyncio.gather(*[_fetch_rss(u, timeout=7) for u in urls], return_exceptions=True)
    for res in results:
        if isinstance(res, Exception):
            continue
        feeds.append(res)

    for feed in feeds:
        for entry in feed.entries or []:
            it = _normalize_entry(entry)
            if not it:
                continue
            if not _within_days(it.get("published_at"), days_back):
                continue
            # boost si menciona la ciudad
            it["_city_hit"] = _score_city_hit(it["title"], it.get("summary",""), city)
            if it["id"] in seen_ids:
                continue
            seen_ids.add(it["id"])
            collected.append(it)
            # Stop early if we already have enough candidates
            if len(collected) >= max(limit * 2, limit):
                break
        if len(collected) >= max(limit * 2, limit):
            break


    # --- Nueva puntuación: prioriza actor (query) sobre ciudad ---
    def _score_item(it: dict, query: str) -> float:
        title = (it.get("title") or "").lower()
        summary = (it.get("summary") or "").lower()
        blob = f"{title}\n{summary}"
        # actor_hit: cualquier token significativo del query presente
        q_tokens = [t for t in re.split(r"\W+", (query or "").lower()) if len(t) >= 3]
        actor_hits = sum(1 for t in q_tokens if t and t in blob)
        actor_score = 1.0 if actor_hits > 0 else 0.0
        # city_hit viene del pipeline previo
        city_hit = 1.0 if (it.get("_city_hit") or 0) else 0.0
        # fecha
        dt = it.get("published_at")
        recency = 0.0
        try:
            # penalización leve si no hay fecha
            recency = 0.1 if dt else 0.0
        except Exception:
            pass
        # ponderación: actor tiene el doble de peso que ciudad
        return (2.0 * actor_score) + (1.0 * city_hit) + recency
    # Orden básico: menciona ciudad primero, luego por fecha desc si hay
    collected.sort(key=lambda x: _score_item(x, query), reverse=True)

    # Re-rank opcional con OpenAI
    top = _rerank_with_openai(collected, query, city, top_k=min(limit, 50))
    # Recorta y limpia campos internos
    cleaned = []
    for it in top[:limit]:
        it.pop("_city_hit", None)
        cleaned.append(it)
    return cleaned
