# app/services/search_local.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import hashlib

from sqlalchemy.orm import Session

# Ajusta a tus modelos reales
from app.db.models import Article, Source  # <-- usa tus modelos reales
# si tus modelos se llaman distinto, cambia los import

NormalizedItem = Dict[str, Any]

def _canon_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    u = url.strip()
    if u.startswith("http://"):
        u = "https://" + u[len("http://"):]
    return u

def _hash_key(title: str, url: Optional[str]) -> str:
    base = f"{title.strip().lower()}|{(url or '').strip().lower()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def _upsert_source(db: Session, name: str) -> Source:
    src = db.query(Source).filter(Source.name == name).first()
    if not src:
        src = Source(name=name)
        db.add(src)
        db.flush()
    return src

def _upsert_article(db: Session, item: NormalizedItem, campaign_id: Optional[str]=None) -> Tuple[Article, bool]:
    """
    Upsert por (hash de titulo+url). Devuelve (article, created_bool)
    """
    title = (item.get("title") or "").strip()
    url   = _canon_url(item.get("url"))
    key   = _hash_key(title, url)

    art = db.query(Article).filter(Article.dedupe_key == key).first()
    created = False
    if not art:
        art = Article(dedupe_key=key)
        created = True

    art.title = title or art.title
    art.url = url or art.url
    art.summary = item.get("summary") or art.summary
    art.source_name = item.get("source") or art.source_name
    art.published_at = item.get("published_at") or art.published_at
    art.country = item.get("country") or art.country
    art.lang = item.get("lang") or art.lang
    art.raw = item.get("raw") or art.raw

    # Si tu modelo relaciona campaña-artículo, ajusta aquí:
    if campaign_id and hasattr(art, "campaign_id"):
        art.campaign_id = campaign_id

    if created:
        db.add(art)
    return art, created

# ============ Proveedores (placeholders) ============

async def search_google_news(q: str, country: str, lang: str, size: int) -> List[NormalizedItem]:
    # TODO: aquí llamas a tu cliente real (que ya usan) o a un microservicio
    return []

async def search_web_generic(q: str, country: str, lang: str, size: int) -> List[NormalizedItem]:
    # TODO: integra SERP API / Custom Search / tu scraper ya existente
    return []

async def search_local_publishers(q: str, country: str, lang: str, size: int) -> List[NormalizedItem]:
    # TODO: una lista curada de medios locales por estado/municipio
    return []

# ============ Orquestador ============

async def run_local_search_and_store(
    db: Session,
    q: str,
    *,
    country: str = "MX",
    lang: str = "es-419",
    size: int = 25,
    campaign_id: Optional[str] = None,
    sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Ejecuta N fuentes, normaliza, de-dupea y guarda.
    """
    sources = sources or ["google_news", "web_generic", "local_publishers"]

    collected: List[NormalizedItem] = []

    if "google_news" in sources:
        collected += await search_google_news(q, country, lang, size)

    if "web_generic" in sources:
        collected += await search_web_generic(q, country, lang, size)

    if "local_publishers" in sources:
        collected += await search_local_publishers(q, country, lang, size)

    # Normalización mínima + de-dupe en memoria por hash (título+url):
    uniq: Dict[str, NormalizedItem] = {}
    for it in collected:
        title = (it.get("title") or "").strip()
        url = _canon_url(it.get("url"))
        key = _hash_key(title, url)
        if key not in uniq:
            # normaliza campos comunes
            norm = {
                "title": title,
                "url": url,
                "summary": it.get("summary"),
                "source": it.get("source"),
                "published_at": it.get("published_at"),
                "country": country,
                "lang": lang,
                "raw": it,  # guarda todo por si luego lo enriqueces
            }
            uniq[key] = norm

    created = 0
    updated = 0
    for item in uniq.values():
        art, was_created = _upsert_article(db, item, campaign_id=campaign_id)
        created += 1 if was_created else 0
        updated += 0 if was_created else 1

    db.commit()

    return {
        "query": q,
        "country": country,
        "lang": lang,
        "requested": size,
        "sources_used": sources,
        "inserted": created,
        "updated": updated,
        "total_unique": len(uniq),
    }