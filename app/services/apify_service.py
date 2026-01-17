# app/services/apify_service.py
"""
Servicio de integración con Apify para monitoreo de redes sociales.
Permite ejecutar Actors de Apify para extraer posts de Facebook, Twitter, Instagram, etc.
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from apify_client import ApifyClient

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURACIÓN
# ============================================================================
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

# Actores de Apify recomendados por plataforma
APIFY_ACTORS = {
    "facebook": "apify/facebook-posts-scraper",
    "twitter": "apify/twitter-scraper",
    "instagram": "apify/instagram-scraper",
    "tiktok": "clockworks/tiktok-scraper",
    "youtube": "bernardo/youtube-scraper",
}

# Límites por defecto
DEFAULT_MAX_POSTS = 50
DEFAULT_DAYS_BACK = 1  # Solo últimas 24 horas


# ============================================================================
# CLIENTE DE APIFY
# ============================================================================
def get_apify_client() -> ApifyClient:
    """Obtiene un cliente de Apify configurado"""
    if not APIFY_API_TOKEN:
        raise ValueError("APIFY_API_TOKEN no está configurado en las variables de entorno")
    return ApifyClient(APIFY_API_TOKEN)


# ============================================================================
# FUNCIONES DE SCRAPING POR PLATAFORMA
# ============================================================================
async def scrape_facebook_page(
    page_url: str,
    candidate_name: str,
    max_posts: int = DEFAULT_MAX_POSTS,
    days_back: int = DEFAULT_DAYS_BACK,
) -> List[Dict[str, Any]]:
    """
    Extrae posts de una página de Facebook que mencionen al candidato.

    Args:
        page_url: URL de la página de Facebook
        candidate_name: Nombre del candidato para filtrar posts
        max_posts: Número máximo de posts a extraer
        days_back: Días hacia atrás para buscar

    Returns:
        Lista de posts con su contenido y métricas
    """
    client = get_apify_client()

    # Calcular fecha límite
    since_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

    # Configuración del Actor de Facebook
    run_input = {
        "startUrls": [{"url": page_url}],
        "maxPosts": max_posts,
        "maxPostDate": since_date,
        "maxComments": 0,  # No queremos comentarios por ahora
        "maxReviews": 0,
        "resultsLimit": max_posts,
    }

    logger.info(f"🔵 Iniciando scraping de Facebook: {page_url}")
    logger.info(f"   Candidato: {candidate_name}, Posts máx: {max_posts}, Desde: {since_date}")

    try:
        # Ejecutar el Actor
        run = client.actor(APIFY_ACTORS["facebook"]).call(run_input=run_input)

        # Obtener resultados
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

        # Filtrar posts que mencionen al candidato
        filtered_posts = []
        candidate_lower = candidate_name.lower()

        for item in items:
            post_text = (item.get("text") or "").lower()
            post_title = (item.get("title") or "").lower()

            # Verificar si el post menciona al candidato
            if candidate_lower in post_text or candidate_lower in post_title:
                filtered_posts.append(_normalize_facebook_post(item))

        logger.info(f"✅ Facebook: {len(items)} posts encontrados, {len(filtered_posts)} relevantes")
        return filtered_posts

    except Exception as e:
        logger.error(f"❌ Error en scraping de Facebook: {e}")
        raise


async def scrape_twitter_account(
    account_url: str,
    candidate_name: str,
    max_posts: int = DEFAULT_MAX_POSTS,
    days_back: int = DEFAULT_DAYS_BACK,
) -> List[Dict[str, Any]]:
    """
    Extrae tweets de una cuenta de Twitter/X que mencionen al candidato.
    """
    client = get_apify_client()

    # Extraer username de la URL
    username = account_url.rstrip("/").split("/")[-1].replace("@", "")

    run_input = {
        "handles": [username],
        "maxTweets": max_posts,
        "mode": "user",
        "addUserInfo": True,
    }

    logger.info(f"🐦 Iniciando scraping de Twitter: @{username}")

    try:
        run = client.actor(APIFY_ACTORS["twitter"]).call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

        # Filtrar por fecha y relevancia
        filtered_posts = []
        candidate_lower = candidate_name.lower()
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)

        for item in items:
            # Verificar fecha
            created_at = item.get("createdAt")
            if created_at:
                try:
                    post_date = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    if post_date < cutoff_date:
                        continue
                except (ValueError, AttributeError):
                    pass

            # Verificar relevancia
            tweet_text = (item.get("text") or "").lower()
            if candidate_lower in tweet_text:
                filtered_posts.append(_normalize_twitter_post(item))

        logger.info(f"✅ Twitter: {len(items)} tweets encontrados, {len(filtered_posts)} relevantes")
        return filtered_posts

    except Exception as e:
        logger.error(f"❌ Error en scraping de Twitter: {e}")
        raise


async def scrape_instagram_profile(
    profile_url: str,
    candidate_name: str,
    max_posts: int = DEFAULT_MAX_POSTS,
    days_back: int = DEFAULT_DAYS_BACK,
) -> List[Dict[str, Any]]:
    """
    Extrae posts de un perfil de Instagram que mencionen al candidato.
    """
    client = get_apify_client()

    run_input = {
        "directUrls": [profile_url],
        "resultsLimit": max_posts,
        "resultsType": "posts",
    }

    logger.info(f"📸 Iniciando scraping de Instagram: {profile_url}")

    try:
        run = client.actor(APIFY_ACTORS["instagram"]).call(run_input=run_input)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

        # Filtrar por relevancia
        filtered_posts = []
        candidate_lower = candidate_name.lower()

        for item in items:
            caption = (item.get("caption") or "").lower()
            if candidate_lower in caption:
                filtered_posts.append(_normalize_instagram_post(item))

        logger.info(f"✅ Instagram: {len(items)} posts encontrados, {len(filtered_posts)} relevantes")
        return filtered_posts

    except Exception as e:
        logger.error(f"❌ Error en scraping de Instagram: {e}")
        raise


# ============================================================================
# FUNCIÓN PRINCIPAL DE SCRAPING
# ============================================================================
async def scrape_monitoring_source(
    url: str,
    platform: str,
    candidate_name: str,
    max_posts: int = DEFAULT_MAX_POSTS,
    days_back: int = DEFAULT_DAYS_BACK,
) -> Dict[str, Any]:
    """
    Función principal que ejecuta el scraping según la plataforma.

    Args:
        url: URL de la fuente a monitorear
        platform: Plataforma (facebook, twitter, instagram, etc.)
        candidate_name: Nombre del candidato para filtrar
        max_posts: Número máximo de posts
        days_back: Días hacia atrás

    Returns:
        Diccionario con posts y metadata
    """
    platform = platform.lower()

    scrapers = {
        "facebook": scrape_facebook_page,
        "twitter": scrape_twitter_account,
        "instagram": scrape_instagram_profile,
    }

    if platform not in scrapers:
        raise ValueError(f"Plataforma no soportada: {platform}")

    try:
        posts = await scrapers[platform](
            url,
            candidate_name,
            max_posts,
            days_back,
        )

        return {
            "success": True,
            "platform": platform,
            "url": url,
            "posts_count": len(posts),
            "posts": posts,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        return {
            "success": False,
            "platform": platform,
            "url": url,
            "error": str(e),
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }


async def scrape_campaign_sources(
    sources: List[Dict[str, Any]],
    candidate_name: str,
    max_posts_per_source: int = DEFAULT_MAX_POSTS,
    days_back: int = DEFAULT_DAYS_BACK,
) -> Dict[str, Any]:
    """
    Ejecuta scraping para todas las fuentes de una campaña.

    Args:
        sources: Lista de fuentes con url y platform
        candidate_name: Nombre del candidato
        max_posts_per_source: Posts máximos por fuente
        days_back: Días hacia atrás

    Returns:
        Resultados agregados de todas las fuentes
    """
    logger.info(f"🚀 Iniciando scraping de campaña: {len(sources)} fuentes")

    all_results = []
    total_posts = 0
    successful = 0
    failed = 0

    for source in sources:
        result = await scrape_monitoring_source(
            url=source["url"],
            platform=source["platform"],
            candidate_name=candidate_name,
            max_posts=max_posts_per_source,
            days_back=days_back,
        )

        all_results.append(result)

        if result["success"]:
            successful += 1
            total_posts += result["posts_count"]
        else:
            failed += 1

    logger.info(f"📊 Scraping completado: {successful} exitosos, {failed} fallidos, {total_posts} posts totales")

    return {
        "total_sources": len(sources),
        "successful": successful,
        "failed": failed,
        "total_posts": total_posts,
        "results": all_results,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


# ============================================================================
# FUNCIONES DE NORMALIZACIÓN
# ============================================================================
def _normalize_facebook_post(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza un post de Facebook al formato estándar"""
    return {
        "platform": "facebook",
        "post_id": item.get("postId"),
        "url": item.get("url"),
        "content": item.get("text"),
        "author": item.get("user", {}).get("name") if isinstance(item.get("user"), dict) else None,
        "date": item.get("time"),
        "likes": item.get("likes"),
        "shares": item.get("shares"),
        "comments": item.get("comments"),
        "views": item.get("views"),
        "raw_data": item,
    }


def _normalize_twitter_post(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza un tweet al formato estándar"""
    return {
        "platform": "twitter",
        "post_id": item.get("id"),
        "url": item.get("url"),
        "content": item.get("text"),
        "author": item.get("author", {}).get("username") if isinstance(item.get("author"), dict) else None,
        "date": item.get("createdAt"),
        "likes": item.get("likeCount"),
        "shares": item.get("retweetCount"),
        "comments": item.get("replyCount"),
        "views": item.get("viewCount"),
        "raw_data": item,
    }


def _normalize_instagram_post(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza un post de Instagram al formato estándar"""
    return {
        "platform": "instagram",
        "post_id": item.get("id"),
        "url": item.get("url"),
        "content": item.get("caption"),
        "author": item.get("ownerUsername"),
        "date": item.get("timestamp"),
        "likes": item.get("likesCount"),
        "shares": None,  # Instagram no tiene shares públicos
        "comments": item.get("commentsCount"),
        "views": item.get("videoViewCount"),
        "raw_data": item,
    }


# ============================================================================
# EJEMPLO DE JSON PARA PERPLEXITY
# ============================================================================
def get_perplexity_analysis_prompt(posts: List[Dict[str, Any]], candidate_name: str) -> Dict[str, Any]:
    """
    Genera el prompt estructurado para enviar a Perplexity.
    Este es el formato óptimo para obtener análisis de percepción.

    Returns:
        Diccionario con el prompt y configuración para Perplexity
    """
    # Preparar contenido de posts para análisis
    posts_content = []
    for i, post in enumerate(posts[:20], 1):  # Máximo 20 posts para optimizar tokens
        posts_content.append({
            "id": i,
            "platform": post.get("platform"),
            "content": (post.get("content") or "")[:500],  # Limitar contenido
            "engagement": {
                "likes": post.get("likes", 0),
                "shares": post.get("shares", 0),
                "comments": post.get("comments", 0),
            }
        })

    return {
        "model": "sonar-pro",  # o "sonar" para menor costo
        "messages": [
            {
                "role": "system",
                "content": """Eres un analista político experto en percepción pública y comunicación política.
Analiza los posts de redes sociales y proporciona un análisis estructurado en JSON.

Tu respuesta DEBE ser un JSON válido con esta estructura exacta:
{
    "summary": "Resumen ejecutivo de 2-3 oraciones",
    "sentiment": {
        "overall": "positive|negative|neutral",
        "score": -1.0 a 1.0,
        "breakdown": {
            "positive": número de posts positivos,
            "negative": número de posts negativos,
            "neutral": número de posts neutros
        }
    },
    "narratives": [
        {
            "topic": "Tema principal",
            "description": "Descripción breve",
            "sentiment": "positive|negative|neutral",
            "frequency": número de menciones
        }
    ],
    "risk_assessment": {
        "level": "low|medium|high|critical",
        "score": 0-100,
        "factors": ["factor1", "factor2"],
        "recommendations": ["recomendación1", "recomendación2"]
    },
    "entities_mentioned": ["entidad1", "entidad2"],
    "key_insights": ["insight1", "insight2", "insight3"]
}"""
            },
            {
                "role": "user",
                "content": f"""Analiza los siguientes posts de redes sociales sobre el candidato/político: {candidate_name}

POSTS A ANALIZAR:
{_format_posts_for_analysis(posts_content)}

Proporciona el análisis en formato JSON siguiendo la estructura indicada.
Enfócate en:
1. Identificar el sentimiento predominante hacia {candidate_name}
2. Detectar narrativas y temas recurrentes
3. Evaluar posibles riesgos reputacionales o crisis
4. Identificar oportunidades de comunicación

Responde SOLO con el JSON, sin texto adicional."""
            }
        ],
        "temperature": 0.1,  # Baja temperatura para respuestas más consistentes
        "max_tokens": 2000,
    }


def _format_posts_for_analysis(posts: List[Dict[str, Any]]) -> str:
    """Formatea los posts para incluir en el prompt"""
    formatted = []
    for post in posts:
        engagement = post.get("engagement", {})
        formatted.append(
            f"[{post['id']}] ({post['platform']}) "
            f"Likes: {engagement.get('likes', 0)}, "
            f"Shares: {engagement.get('shares', 0)}, "
            f"Comments: {engagement.get('comments', 0)}\n"
            f"Contenido: {post['content']}\n"
        )
    return "\n---\n".join(formatted)
