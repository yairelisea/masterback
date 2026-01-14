# app/routers/url_analyzer.py
"""
Router para el Analizador de Percepción Digital.
Solo accesible para usuarios admin.
Permite analizar URLs para evaluar sentimiento, toxicidad y oportunidades políticas.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
from collections import Counter
from io import BytesIO
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Response, Body
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from weasyprint import HTML

from app.db import get_session
from app.models import Campaign, IngestedItem
from app.schemas import (
    AnalyzeURLRequest,
    AnalyzeURLResponse,
    Politician,
    PostAI,
    PostMeta,
    PostResult,
)
from app.middleware import get_current_user

router = APIRouter(prefix="/url-analyzer", tags=["url-analyzer"])

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "5"))
PER_URL_DEADLINE = int(os.getenv("PER_URL_DEADLINE", "20"))
MIN_URLS = int(os.getenv("MIN_URLS", "5"))

# Cache de texto para evitar reanálisis
_TEXT_CACHE: Dict[str, Dict[str, Any]] = {}

# ──────────────────────────────────────────────────────────────────────────────
# Utils
# ──────────────────────────────────────────────────────────────────────────────
def sanitize_url(u: str) -> str:
    """Sanitiza una URL para evitar variaciones triviales"""
    u = (u or "").strip()
    if u.startswith("http://"):
        u = "https://" + u[len("http://"):]
    return u


def detect_platform(u: str) -> str:
    """Detecta la plataforma de una URL"""
    s = u.lower()
    if "facebook.com" in s:
        return "facebook"
    if "instagram.com" in s:
        return "instagram"
    if "twitter.com" in s or "x.com" in s:
        return "twitter"
    if "tiktok.com" in s:
        return "tiktok"
    if "youtube.com" in s or "youtu.be" in s:
        return "youtube"
    return "web"


def safe_text(*parts):
    """Retorna el primer texto válido de los argumentos"""
    for p in parts:
        if p and isinstance(p, str) and len(p.strip()) >= 40:
            return p.strip()
    for p in parts:
        if p and isinstance(p, str) and len(p.strip()) > 0:
            return p.strip()
    return ""


def _escape(s):
    """Escapa HTML para PDF"""
    try:
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    except Exception:
        return ""


def _clip(s: Optional[str], n: int) -> str:
    """Recorta texto a n caracteres"""
    if not s:
        return ""
    s = str(s)
    return s if len(s) <= n else s[:n]


def build_summary_counts(results: List[PostResult]):
    """Construye resumen estadístico de resultados"""
    sentiments = Counter(
        getattr(r.ai, "sentiment", None) for r in results if getattr(r, "ai", None)
    )
    stances = Counter(
        getattr(r.ai, "stance", None) for r in results if getattr(r, "ai", None)
    )
    if None in sentiments:
        sentiments.pop(None)
    if None in stances:
        stances.pop(None)
    entities = Counter(
        e for r in results for e in (getattr(r.ai, "entities", []) or [])
    )
    total = len(results)
    predominant = max(sentiments, key=sentiments.get) if sentiments else "neutral"
    top_entities = [f"{name} ({cnt})" for name, cnt in entities.most_common(5)]

    return {
        "total": total,
        "sentiments": dict(sentiments) if sentiments else {},
        "predominant": predominant,
        "stances": dict(stances) if stances else {},
        "top_entities": top_entities if top_entities else [],
        "results": [],
    }


def make_short_exec_summary(politician_name: str, counts: dict) -> str:
    """Genera un resumen narrativo de la percepción pública"""
    total = counts.get("total", 0)
    sents = counts.get("sentiments") or {}
    st = counts.get("stances") or {}
    ents = counts.get("top_entities") or []
    predominant = counts.get("predominant", "neutral")

    pos_count = sents.get("positive", 0)
    neg_count = sents.get("negative", 0)
    neu_count = sents.get("neutral", 0)

    favor_count = st.get("favor", 0)
    against_count = st.get("against", 0)

    paragraphs = []

    if total == 0:
        return f"No se encontraron publicaciones recientes sobre {politician_name} en el período analizado."

    if total == 1:
        intro = f"Se identificó una publicación sobre {politician_name} en medios digitales."
    elif total < 5:
        intro = f"Se monitorearon {total} publicaciones sobre {politician_name} en medios digitales."
    else:
        intro = f"Durante el período analizado se registraron {total} publicaciones sobre {politician_name} en diversos medios digitales."

    paragraphs.append(intro)

    if predominant == "positive":
        if pos_count > total * 0.7:
            sentiment_text = "La percepción pública es mayormente favorable, con la amplia mayoría de las menciones destacando aspectos positivos de su gestión o propuestas."
        elif pos_count > total * 0.5:
            sentiment_text = f"El tono predominante en las publicaciones es favorable hacia {politician_name}, aunque existe un segmento de opiniones mixtas."
        else:
            sentiment_text = "Se observa una tendencia positiva en las menciones, aunque con cierta diversidad de opiniones en el espacio digital."
    elif predominant == "negative":
        if neg_count > total * 0.7:
            sentiment_text = "La percepción en medios digitales es predominantemente crítica, con cuestionamientos significativos hacia su gestión o propuestas."
        elif neg_count > total * 0.5:
            sentiment_text = "El tono crítico predomina en las publicaciones analizadas, reflejando controversias o desacuerdos con sus acciones recientes."
        else:
            sentiment_text = "Se identifican señales de percepción negativa, aunque coexisten con opiniones más equilibradas en el espacio público."
    else:
        if neu_count > total * 0.7:
            sentiment_text = "Las publicaciones mantienen un tono mayormente informativo y equilibrado, sin inclinaciones marcadas a favor o en contra."
        else:
            sentiment_text = "La cobertura presenta una mezcla de perspectivas, sin un consenso claro sobre su imagen pública en este período."

    paragraphs.append(sentiment_text)

    if favor_count > 0 or against_count > 0:
        if favor_count > against_count * 2:
            stance_text = f"En términos de posicionamiento, el respaldo hacia {politician_name} es notablemente superior a las voces críticas, sugiriendo una base de apoyo consolidada."
        elif against_count > favor_count * 2:
            stance_text = "La oposición a sus acciones o propuestas es significativamente más visible que el apoyo explícito, evidenciando resistencia en sectores de la opinión pública."
        elif abs(favor_count - against_count) <= total * 0.1:
            stance_text = "Se observa una polarización equilibrada, con voces a favor y en contra en proporciones similares, reflejando un escenario de debate activo."
        else:
            stance_text = "Existe un debate moderado en el espacio público, con distintas posturas que coexisten sin una clara mayoría."

        paragraphs.append(stance_text)

    if ents:
        entity_names = [e.split(" (")[0] for e in ents[:3]]
        if len(entity_names) == 1:
            entities_text = f"La conversación se centra principalmente en la relación con {entity_names[0]}."
        elif len(entity_names) == 2:
            entities_text = f"Las menciones frecuentemente involucran a {entity_names[0]} y {entity_names[1]}, indicando conexiones relevantes en el contexto actual."
        else:
            entities_text = f"Las publicaciones mencionan recurrentemente a {', '.join(entity_names[:-1])} y {entity_names[-1]}, reflejando un ecosistema de actores interconectados."

        paragraphs.append(entities_text)

    conclusion = "Este análisis se basa en contenido público disponible en medios digitales. Para métricas precisas de redes sociales, se requieren APIs oficiales de las plataformas."
    paragraphs.append(conclusion)

    return "\n\n".join(paragraphs)


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline de análisis
# ──────────────────────────────────────────────────────────────────────────────
async def _analyze_all(req: AnalyzeURLRequest) -> List[PostResult]:
    """
    Analiza todas las URLs de manera asíncrona.
    NOTA: Esta función requiere los servicios 'fetcher' y análisis de IA.
    Por ahora, retorna datos simulados para testing.
    """
    # TODO: Implementar integración real con servicios de fetcher y Perplexity
    # Importar cuando estén disponibles:
    # from app.services.fetcher import fetch_page
    # from app.services.perplexity import analyze_text, analyze_facebook_url

    results = []

    for url in req.urls:
        safe_u = sanitize_url(str(url))
        platform = detect_platform(safe_u)

        # Datos simulados para testing
        meta = PostMeta(
            platform=platform,
            url=safe_u,
            title=f"Post en {platform}",
            description="Análisis pendiente de integración con servicios",
            debug="mock-data",
        )

        ai = PostAI(
            summary="Análisis pendiente. Integrar servicios de Perplexity y Fetcher.",
            topic="general",
            sentiment="neutral",
            stance="none",
            entities=[req.politician.name],
            toxicity=0,
        )

        results.append(PostResult(meta=meta, ai=ai))

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/campaign/{campaign_id}/urls")
async def get_campaign_urls_for_analysis(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Obtiene todas las URLs de una campaña para análisis.
    Solo accesible para admins.
    """
    # Verificar que el usuario sea admin
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    c = await db.get(Campaign, campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Obtener todas las URLs de IngestedItem
    q = (
        select(IngestedItem.url, IngestedItem.title)
        .where(IngestedItem.campaignId == campaign_id)
        .distinct()
        .limit(200)
    )
    result = await db.execute(q)
    rows = result.all()

    urls_data = [{"url": row.url, "title": row.title} for row in rows]

    return {
        "campaign_id": campaign_id,
        "campaign_name": c.name,
        "total_urls": len(urls_data),
        "urls": urls_data,
    }


@router.post("/analyze", response_model=AnalyzeURLResponse)
async def analyze_urls(
    req: AnalyzeURLRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Analiza un conjunto de URLs para percepción política.
    Solo accesible para admins.
    """
    # Verificar que el usuario sea admin
    if not current_user.get("isAdmin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    if len(req.urls) < MIN_URLS:
        raise HTTPException(
            400,
            detail=f"Se requieren ≥{MIN_URLS} URLs; recibidas: {len(req.urls)}",
        )

    results = await _analyze_all(req)
    counts = build_summary_counts(results)
    short_text = make_short_exec_summary(req.politician.name, counts)
    summary = {**counts, "short_text": short_text}

    return AnalyzeURLResponse(
        politician=req.politician,
        results=results,
        summary=summary,
        metadata={
            "total_urls": len(req.urls),
            "successful_analyses": len(results),
        },
    )


@router.get("/health")
async def url_analyzer_health():
    """Health check para el analizador de URLs"""
    return {
        "ok": True,
        "service": "URL Analyzer",
        "status": "active",
        "note": "Servicios de Perplexity y Fetcher pendientes de integración",
    }
