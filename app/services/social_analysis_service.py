# app/services/social_analysis_service.py
"""
Servicio de análisis de percepción para posts de redes sociales.
Integra los datos de Apify con la API de Perplexity para análisis de IA.
"""
from __future__ import annotations

import os
import json
import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import (
    Campaign,
    MonitoringSource,
    AnalyticResult,
    ApifyRun,
    ApifyRunStatus,
    RiskLevel,
    MonitoringStatus,
)
from app.services.apify_service import (
    scrape_monitoring_source,
    scrape_campaign_sources,
    get_perplexity_analysis_prompt,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURACIÓN
# ============================================================================
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

# Configuración de análisis
MIN_POSTS_FOR_ANALYSIS = 3  # Mínimo de posts para justificar llamada a IA
MAX_POSTS_PER_BATCH = 20  # Máximo de posts por llamada a Perplexity
RELEVANCE_THRESHOLD = 0.3  # Score mínimo para considerar un post relevante


# ============================================================================
# ANÁLISIS CON PERPLEXITY
# ============================================================================
async def analyze_posts_with_perplexity(
    posts: List[Dict[str, Any]],
    candidate_name: str,
) -> Dict[str, Any]:
    """
    Analiza una lista de posts usando la API de Perplexity.

    Args:
        posts: Lista de posts normalizados de Apify
        candidate_name: Nombre del candidato/político

    Returns:
        Diccionario con el análisis estructurado
    """
    if not PERPLEXITY_API_KEY:
        raise ValueError("PERPLEXITY_API_KEY no está configurado")

    if len(posts) < MIN_POSTS_FOR_ANALYSIS:
        logger.warning(f"⚠️ Solo {len(posts)} posts, insuficiente para análisis profundo")
        return _generate_basic_analysis(posts, candidate_name)

    # Limitar posts para optimizar tokens
    posts_to_analyze = posts[:MAX_POSTS_PER_BATCH]

    # Generar prompt
    prompt_config = get_perplexity_analysis_prompt(posts_to_analyze, candidate_name)

    logger.info(f"🤖 Enviando {len(posts_to_analyze)} posts a Perplexity para análisis")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                PERPLEXITY_API_URL,
                headers={
                    "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=prompt_config,
            )
            response.raise_for_status()
            result = response.json()

        # Extraer respuesta
        ai_response = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parsear JSON de la respuesta
        analysis = _parse_ai_response(ai_response)

        # Agregar metadata
        analysis["metadata"] = {
            "posts_analyzed": len(posts_to_analyze),
            "total_posts": len(posts),
            "model": prompt_config.get("model"),
            "tokens_used": result.get("usage", {}).get("total_tokens"),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(f"✅ Análisis completado: sentimiento={analysis.get('sentiment', {}).get('overall')}")
        return analysis

    except httpx.HTTPError as e:
        logger.error(f"❌ Error HTTP en Perplexity: {e}")
        return _generate_error_analysis(str(e), posts, candidate_name)
    except Exception as e:
        logger.error(f"❌ Error en análisis: {e}")
        return _generate_error_analysis(str(e), posts, candidate_name)


def _parse_ai_response(response_text: str) -> Dict[str, Any]:
    """Parsea la respuesta de IA a JSON"""
    try:
        # Intentar parsear directamente
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # Buscar JSON en la respuesta
    json_match = re.search(r'\{[\s\S]*\}', response_text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Si no se puede parsear, crear estructura básica
    logger.warning("⚠️ No se pudo parsear respuesta de IA, usando análisis básico")
    return {
        "summary": response_text[:500] if response_text else "Análisis no disponible",
        "sentiment": {"overall": "neutral", "score": 0.0},
        "narratives": [],
        "risk_assessment": {"level": "low", "score": 0},
        "parse_error": True,
    }


def _generate_basic_analysis(posts: List[Dict[str, Any]], candidate_name: str) -> Dict[str, Any]:
    """Genera un análisis básico sin usar IA (para pocos posts)"""
    return {
        "summary": f"Análisis básico de {len(posts)} posts sobre {candidate_name}. "
                   "Insuficientes datos para análisis profundo.",
        "sentiment": {
            "overall": "neutral",
            "score": 0.0,
            "breakdown": {"positive": 0, "negative": 0, "neutral": len(posts)},
        },
        "narratives": [],
        "risk_assessment": {
            "level": "low",
            "score": 0,
            "factors": ["Datos insuficientes"],
            "recommendations": ["Agregar más fuentes de monitoreo"],
        },
        "entities_mentioned": [candidate_name],
        "key_insights": ["Datos insuficientes para generar insights"],
        "metadata": {
            "posts_analyzed": len(posts),
            "analysis_type": "basic",
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def _generate_error_analysis(error: str, posts: List[Dict[str, Any]], candidate_name: str) -> Dict[str, Any]:
    """Genera un análisis de fallback cuando hay error"""
    return {
        "summary": f"Error durante el análisis de {len(posts)} posts sobre {candidate_name}.",
        "sentiment": {"overall": "unknown", "score": 0.0},
        "narratives": [],
        "risk_assessment": {"level": "unknown", "score": 0},
        "error": error,
        "metadata": {
            "posts_analyzed": 0,
            "analysis_type": "error_fallback",
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        },
    }


# ============================================================================
# PIPELINE COMPLETO: APIFY → PERPLEXITY → BD
# ============================================================================
async def run_campaign_monitoring_pipeline(
    campaign_id: str,
    db: AsyncSession,
    days_back: int = 1,
    max_posts_per_source: int = 50,
) -> Dict[str, Any]:
    """
    Pipeline completo de monitoreo:
    1. Obtiene fuentes de la campaña
    2. Ejecuta scraping con Apify
    3. Analiza con Perplexity
    4. Guarda resultados en BD

    Args:
        campaign_id: ID de la campaña
        db: Sesión de base de datos
        days_back: Días hacia atrás para buscar
        max_posts_per_source: Posts máximos por fuente

    Returns:
        Resumen de la ejecución
    """
    logger.info(f"🚀 Iniciando pipeline de monitoreo para campaña: {campaign_id}")

    # 1. Obtener campaña y fuentes
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError(f"Campaña no encontrada: {campaign_id}")

    candidate_name = campaign.name  # Usar nombre de campaña como nombre del candidato

    # Obtener fuentes activas
    sources_query = select(MonitoringSource).where(
        MonitoringSource.campaignId == campaign_id,
        MonitoringSource.status == MonitoringStatus.ACTIVE,
    )
    result = await db.execute(sources_query)
    sources = result.scalars().all()

    if not sources:
        logger.warning(f"⚠️ No hay fuentes activas para la campaña {campaign_id}")
        return {
            "success": False,
            "message": "No hay fuentes de monitoreo activas",
            "campaign_id": campaign_id,
        }

    # 2. Crear registro de ejecución de Apify
    apify_run = ApifyRun(
        apifyRunId=f"local-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        campaignId=campaign_id,
        actorId="multi-platform",
        status=ApifyRunStatus.RUNNING,
        startedAt=datetime.now(timezone.utc),
        inputConfig={
            "sources_count": len(sources),
            "days_back": days_back,
            "max_posts_per_source": max_posts_per_source,
        },
    )
    db.add(apify_run)
    await db.flush()

    try:
        # 3. Ejecutar scraping
        sources_data = [
            {"url": s.url, "platform": s.platform.value}
            for s in sources
        ]

        scrape_result = await scrape_campaign_sources(
            sources=sources_data,
            candidate_name=candidate_name,
            max_posts_per_source=max_posts_per_source,
            days_back=days_back,
        )

        # 4. Recopilar todos los posts
        all_posts = []
        source_map = {s.url: s for s in sources}

        for source_result in scrape_result.get("results", []):
            if source_result.get("success"):
                source_url = source_result.get("url")
                source_obj = source_map.get(source_url)

                for post in source_result.get("posts", []):
                    post["source_id"] = source_obj.id if source_obj else None
                    all_posts.append(post)

                # Actualizar fuente
                if source_obj:
                    source_obj.lastRunAt = datetime.now(timezone.utc)
                    source_obj.lastRunStatus = "success"
                    source_obj.lastRunPostsCount = len(source_result.get("posts", []))
                    source_obj.totalPostsCollected += len(source_result.get("posts", []))
            else:
                source_url = source_result.get("url")
                source_obj = source_map.get(source_url)
                if source_obj:
                    source_obj.lastRunAt = datetime.now(timezone.utc)
                    source_obj.lastRunStatus = "error"
                    source_obj.lastError = source_result.get("error")
                    source_obj.errorCount += 1

        logger.info(f"📊 Scraping completado: {len(all_posts)} posts totales")

        # 5. Analizar con Perplexity
        analysis = await analyze_posts_with_perplexity(all_posts, candidate_name)

        # 6. Guardar resultados en BD
        results_saved = 0
        for post in all_posts:
            analytic_result = _create_analytic_result(
                post=post,
                campaign_id=campaign_id,
                analysis=analysis,
            )
            db.add(analytic_result)
            results_saved += 1

        # 7. Actualizar registro de ejecución
        apify_run.status = ApifyRunStatus.SUCCEEDED
        apify_run.finishedAt = datetime.now(timezone.utc)
        apify_run.postsFound = len(all_posts)
        apify_run.postsAnalyzed = results_saved

        await db.commit()

        logger.info(f"✅ Pipeline completado: {results_saved} resultados guardados")

        return {
            "success": True,
            "campaign_id": campaign_id,
            "candidate_name": candidate_name,
            "sources_processed": len(sources),
            "posts_found": len(all_posts),
            "results_saved": results_saved,
            "analysis_summary": {
                "sentiment": analysis.get("sentiment", {}).get("overall"),
                "risk_level": analysis.get("risk_assessment", {}).get("level"),
                "narratives_count": len(analysis.get("narratives", [])),
            },
            "apify_run_id": apify_run.id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        logger.error(f"❌ Error en pipeline: {e}")

        # Marcar ejecución como fallida
        apify_run.status = ApifyRunStatus.FAILED
        apify_run.finishedAt = datetime.now(timezone.utc)
        apify_run.errorMessage = str(e)

        await db.commit()

        return {
            "success": False,
            "campaign_id": campaign_id,
            "error": str(e),
            "apify_run_id": apify_run.id,
        }


def _create_analytic_result(
    post: Dict[str, Any],
    campaign_id: str,
    analysis: Dict[str, Any],
) -> AnalyticResult:
    """Crea un AnalyticResult a partir de un post y su análisis"""
    sentiment_data = analysis.get("sentiment", {})
    risk_data = analysis.get("risk_assessment", {})

    # Mapear nivel de riesgo
    risk_level_map = {
        "low": RiskLevel.LOW,
        "medium": RiskLevel.MEDIUM,
        "high": RiskLevel.HIGH,
        "critical": RiskLevel.CRITICAL,
    }
    risk_level = risk_level_map.get(risk_data.get("level", "").lower())

    return AnalyticResult(
        sourceId=post.get("source_id"),
        campaignId=campaign_id,
        postId=post.get("post_id"),
        postUrl=post.get("url"),
        postContent=post.get("content"),
        postAuthor=post.get("author"),
        postDate=_parse_post_date(post.get("date")),
        likes=post.get("likes"),
        shares=post.get("shares"),
        comments=post.get("comments"),
        views=post.get("views"),
        sentiment=sentiment_data.get("overall"),
        sentimentScore=sentiment_data.get("score"),
        riskLevel=risk_level,
        riskScore=risk_data.get("score"),
        riskFactors=risk_data.get("factors"),
        topics=[n.get("topic") for n in analysis.get("narratives", [])],
        entities={"mentioned": analysis.get("entities_mentioned", [])},
        summary=analysis.get("summary"),
        analysisModel=analysis.get("metadata", {}).get("model"),
        analysisTokens=analysis.get("metadata", {}).get("tokens_used"),
        rawApifyData=post.get("raw_data"),
        rawAIResponse=analysis,
        isProcessed=True,
        requiresAttention=risk_data.get("level") in ["high", "critical"],
    )


def _parse_post_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parsea la fecha de un post"""
    if not date_str:
        return None

    try:
        # Intentar varios formatos
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]:
            try:
                return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        # Intentar ISO format
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


# ============================================================================
# FUNCIONES DE CONSULTA
# ============================================================================
async def get_campaign_analysis_summary(
    campaign_id: str,
    db: AsyncSession,
    days_back: int = 7,
) -> Dict[str, Any]:
    """
    Obtiene un resumen del análisis de una campaña.
    """
    from sqlalchemy import func

    # Fecha límite
    cutoff_date = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    cutoff_date = cutoff_date.replace(day=cutoff_date.day - days_back)

    # Query de resultados
    query = select(AnalyticResult).where(
        AnalyticResult.campaignId == campaign_id,
        AnalyticResult.createdAt >= cutoff_date,
    )
    result = await db.execute(query)
    results = result.scalars().all()

    if not results:
        return {
            "campaign_id": campaign_id,
            "total_posts": 0,
            "message": "No hay datos de análisis",
        }

    # Calcular estadísticas
    sentiments = {"positive": 0, "negative": 0, "neutral": 0}
    risk_levels = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    total_engagement = {"likes": 0, "shares": 0, "comments": 0}

    for r in results:
        if r.sentiment:
            sentiments[r.sentiment] = sentiments.get(r.sentiment, 0) + 1
        if r.riskLevel:
            risk_levels[r.riskLevel.value] = risk_levels.get(r.riskLevel.value, 0) + 1
        total_engagement["likes"] += r.likes or 0
        total_engagement["shares"] += r.shares or 0
        total_engagement["comments"] += r.comments or 0

    # Calcular sentimiento predominante
    predominant_sentiment = max(sentiments, key=sentiments.get) if sentiments else "neutral"

    return {
        "campaign_id": campaign_id,
        "period_days": days_back,
        "total_posts": len(results),
        "sentiment": {
            "breakdown": sentiments,
            "predominant": predominant_sentiment,
        },
        "risk": {
            "breakdown": risk_levels,
            "high_risk_count": risk_levels.get("high", 0) + risk_levels.get("critical", 0),
        },
        "engagement": total_engagement,
        "requires_attention": sum(1 for r in results if r.requiresAttention),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
