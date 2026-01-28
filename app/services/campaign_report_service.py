# app/services/campaign_report_service.py
"""
Servicio para generación de reportes diarios y semanales de campañas.
Combina datos de:
- IngestedItems (noticias)
- AnalyticResults (redes sociales + sitios de noticias via Apify)
- Analyses (análisis de sentimiento existentes)

Genera reportes estructurados que pueden ser convertidos a PDF.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Any, Optional
from collections import Counter

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (
    Campaign,
    IngestedItem,
    Analysis,
    AnalyticResult,
    MonitoringSource,
    ActorReport,
    ReportType,
    RiskLevel,
    RawScrapeData,
    CampaignAnalysis,
)

logger = logging.getLogger(__name__)


# ============================================================================
# GENERACIÓN DE REPORTE DIARIO
# ============================================================================
async def generate_daily_report(
    campaign_id: str,
    report_date: date,
    db: AsyncSession,
) -> Dict[str, Any]:
    """
    Genera un reporte diario para una campaña.

    Incluye:
    - Resumen del día
    - Menciones en noticias
    - Menciones en redes sociales
    - Análisis de sentimiento
    - Alertas de riesgo

    Args:
        campaign_id: ID de la campaña
        report_date: Fecha del reporte (default: hoy)
        db: Sesión de base de datos

    Returns:
        Diccionario con el reporte estructurado
    """
    logger.info(f"📊 Generando reporte diario para campaña {campaign_id}, fecha: {report_date}")

    # Obtener campaña
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError(f"Campaña no encontrada: {campaign_id}")

    # Rango de fechas para el día
    start_of_day = datetime.combine(report_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_day = datetime.combine(report_date, datetime.max.time()).replace(tzinfo=timezone.utc)

    # 1. Obtener noticias del día
    news_data = await _get_news_for_period(
        campaign_id=campaign_id,
        start_date=start_of_day,
        end_date=end_of_day,
        db=db,
    )

    # 2. Obtener datos de redes sociales del día (legacy/apify)
    social_data = await _get_social_data_for_period(
        campaign_id=campaign_id,
        start_date=start_of_day,
        end_date=end_of_day,
        db=db,
    )

    # 3. Obtener datos crudos analizados (SOCMINT)
    raw_analyzed_data = await _get_analyzed_raw_data_for_period(
        campaign_id=campaign_id,
        start_date=start_of_day,
        end_date=end_of_day,
        db=db,
    )

    # 3. Calcular métricas agregadas
    sentiment_summary = _calculate_sentiment_summary(news_data, social_data, raw_analyzed_data)
    risk_summary = _calculate_risk_summary(social_data, raw_analyzed_data)
    topics_summary = _extract_top_topics(news_data, social_data, raw_analyzed_data, limit=10)

    # 4. Construir reporte
    report = {
        "report_type": "daily",
        "campaign": {
            "id": campaign.id,
            "name": campaign.name,
            "query": campaign.query,
        },
        "report_date": report_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),

        # Resumen ejecutivo
        "summary": {
            "total_mentions": len(news_data["items"]) + len(social_data["posts"]) + len(raw_analyzed_data["analyses"]),
            "news_count": len(news_data["items"]),
            "social_count": len(social_data["posts"]),
            "socmint_count": len(raw_analyzed_data["analyses"]),
            "sentiment": sentiment_summary,
            "risk_level": risk_summary["level"],
            "risk_score": risk_summary["score"],
        },

        # Datos de noticias
        "news": {
            "count": len(news_data["items"]),
            "sentiment_breakdown": news_data["sentiment_breakdown"],
            "items": news_data["items"][:20],  # Top 20 noticias
        },

        # Datos de redes sociales
        "social": {
            "count": len(social_data["posts"]),
            "by_platform": social_data["by_platform"],
            "sentiment_breakdown": social_data["sentiment_breakdown"],
            "engagement_total": social_data["engagement_total"],
            "top_posts": social_data["posts"][:10],  # Top 10 posts
        },

        # Temas y narrativas
        "topics": topics_summary,

        # Análisis SOCMINT (Datos Crudos Analizados)
        "socmint_analysis": {
            "count": len(raw_analyzed_data["analyses"]),
            "sentiment_breakdown": raw_analyzed_data["sentiment_breakdown"],
            "risk_breakdown": raw_analyzed_data["risk_breakdown"],
            "items": raw_analyzed_data["analyses"][:20],
        },

        # Alertas de riesgo
        "risk_alerts": risk_summary["alerts"],

        # Recomendaciones (si hay riesgo alto)
        "recommendations": risk_summary.get("recommendations", []),
    }

    logger.info(
        f"✅ Reporte diario generado: "
        f"{len(news_data['items'])} noticias, "
        f"{len(social_data['posts'])} posts sociales"
    )

    return report


# ============================================================================
# GENERACIÓN DE REPORTE SEMANAL
# ============================================================================
async def generate_weekly_report(
    campaign_id: str,
    week_end_date: date,
    db: AsyncSession,
) -> Dict[str, Any]:
    """
    Genera un reporte semanal para una campaña.

    Incluye:
    - Resumen de la semana
    - Tendencias de sentimiento día a día
    - Comparativa con semana anterior
    - Análisis de narrativas principales
    - Métricas de engagement
    - Evaluación de riesgos

    Args:
        campaign_id: ID de la campaña
        week_end_date: Último día de la semana (default: hoy)
        db: Sesión de base de datos

    Returns:
        Diccionario con el reporte estructurado
    """
    logger.info(f"📊 Generando reporte semanal para campaña {campaign_id}")

    # Obtener campaña
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError(f"Campaña no encontrada: {campaign_id}")

    # Calcular rango de la semana (7 días)
    week_start_date = week_end_date - timedelta(days=6)
    start_of_week = datetime.combine(week_start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
    end_of_week = datetime.combine(week_end_date, datetime.max.time()).replace(tzinfo=timezone.utc)

    # Semana anterior (para comparativa)
    prev_week_start = start_of_week - timedelta(days=7)
    prev_week_end = start_of_week - timedelta(seconds=1)

    # 1. Datos de la semana actual
    news_data = await _get_news_for_period(campaign_id, start_of_week, end_of_week, db)
    social_data = await _get_social_data_for_period(campaign_id, start_of_week, end_of_week, db)

    # 2. Datos de la semana anterior (para comparativa)
    prev_news = await _get_news_for_period(campaign_id, prev_week_start, prev_week_end, db)
    prev_social = await _get_social_data_for_period(campaign_id, prev_week_start, prev_week_end, db)

    # 3. Datos crudos analizados (SOCMINT) - Semana actual
    raw_analyzed_data = await _get_analyzed_raw_data_for_period(campaign_id, start_of_week, end_of_week, db)
    # Datos crudos analizados (SOCMINT) - Semana anterior
    prev_raw_analyzed = await _get_analyzed_raw_data_for_period(campaign_id, prev_week_start, prev_week_end, db)

    # 3. Calcular tendencia día a día
    daily_trend = await _calculate_daily_trend(
        campaign_id, week_start_date, week_end_date, db
    )

    # 4. Métricas agregadas
    sentiment_summary = _calculate_sentiment_summary(news_data, social_data, raw_analyzed_data)
    risk_summary = _calculate_risk_summary(social_data, raw_analyzed_data)
    topics_summary = _extract_top_topics(news_data, social_data, raw_analyzed_data, limit=15)

    # 5. Comparativa con semana anterior
    comparison = _calculate_week_comparison(
        current_news=news_data,
        current_social=social_data,
        current_raw=raw_analyzed_data,
        prev_news=prev_news,
        prev_social=prev_social,
        prev_raw=prev_raw_analyzed,
    )

    # 6. Construir reporte
    report = {
        "report_type": "weekly",
        "campaign": {
            "id": campaign.id,
            "name": campaign.name,
            "query": campaign.query,
        },
        "period": {
            "start_date": week_start_date.isoformat(),
            "end_date": week_end_date.isoformat(),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),

        # Resumen ejecutivo
        "summary": {
            "total_mentions": len(news_data["items"]) + len(social_data["posts"]) + len(raw_analyzed_data["analyses"]),
            "news_count": len(news_data["items"]),
            "social_count": len(social_data["posts"]),
            "socmint_count": len(raw_analyzed_data["analyses"]),
            "avg_daily_mentions": (len(news_data["items"]) + len(social_data["posts"]) + len(raw_analyzed_data["analyses"])) / 7,
            "sentiment": sentiment_summary,
            "risk_level": risk_summary["level"],
            "risk_score": risk_summary["score"],
        },

        # Comparativa con semana anterior
        "comparison": comparison,

        # Tendencia diaria
        "daily_trend": daily_trend,

        # Datos de noticias
        "news": {
            "count": len(news_data["items"]),
            "sentiment_breakdown": news_data["sentiment_breakdown"],
            "top_stories": news_data["items"][:10],
        },

        # Datos de redes sociales
        "social": {
            "count": len(social_data["posts"]),
            "by_platform": social_data["by_platform"],
            "sentiment_breakdown": social_data["sentiment_breakdown"],
            "engagement_total": social_data["engagement_total"],
            "top_posts": social_data["posts"][:10],
        },

        # Temas principales
        "topics": topics_summary,

        # Análisis SOCMINT (Datos Crudos Analizados)
        "socmint_analysis": {
            "count": len(raw_analyzed_data["analyses"]),
            "sentiment_breakdown": raw_analyzed_data["sentiment_breakdown"],
            "risk_breakdown": raw_analyzed_data["risk_breakdown"],
            "items": raw_analyzed_data["analyses"][:20],
        },

        # Narrativas detectadas
        "narratives": _extract_narratives(social_data),

        # Análisis de riesgo
        "risk_analysis": risk_summary,

        # Insights y recomendaciones
        "insights": _generate_insights(sentiment_summary, comparison, risk_summary),
        "recommendations": risk_summary.get("recommendations", []),
    }

    logger.info(
        f"✅ Reporte semanal generado: "
        f"{len(news_data['items'])} noticias, "
        f"{len(social_data['posts'])} posts sociales, "
        f"{len(daily_trend)} días"
    )

    return report


# ============================================================================
# FUNCIONES AUXILIARES - OBTENCIÓN DE DATOS
# ============================================================================
async def _get_news_for_period(
    campaign_id: str,
    start_date: datetime,
    end_date: datetime,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Obtiene noticias (IngestedItems + Analyses) para un período"""

    query = (
        select(IngestedItem)
        .options(selectinload(IngestedItem.analysis))
        .where(
            IngestedItem.campaignId == campaign_id,
            IngestedItem.createdAt >= start_date,
            IngestedItem.createdAt <= end_date,
        )
        .order_by(IngestedItem.createdAt.desc())
    )

    result = await db.execute(query)
    items = result.scalars().all()

    # Procesar items
    processed_items = []
    sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}

    for item in items:
        item_data = {
            "id": item.id,
            "title": item.title,
            "url": item.url,
            "published_at": item.publishedAt.isoformat() if item.publishedAt else None,
            "created_at": item.createdAt.isoformat() if item.createdAt else None,
        }

        if item.analysis:
            item_data["sentiment"] = item.analysis.tone
            item_data["sentiment_score"] = item.analysis.sentiment
            item_data["summary"] = item.analysis.summary
            item_data["topics"] = item.analysis.topics

            # Contar sentimientos
            tone = (item.analysis.tone or "neutral").lower()
            if "positiv" in tone:
                sentiment_counts["positive"] += 1
            elif "negativ" in tone:
                sentiment_counts["negative"] += 1
            else:
                sentiment_counts["neutral"] += 1

        processed_items.append(item_data)

    return {
        "items": processed_items,
        "sentiment_breakdown": sentiment_counts,
    }


async def _get_social_data_for_period(
    campaign_id: str,
    start_date: datetime,
    end_date: datetime,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Obtiene datos de redes sociales (AnalyticResults) para un período"""

    query = (
        select(AnalyticResult)
        .options(selectinload(AnalyticResult.source))
        .where(
            AnalyticResult.campaignId == campaign_id,
            AnalyticResult.createdAt >= start_date,
            AnalyticResult.createdAt <= end_date,
            AnalyticResult.isRelevant == True,
        )
        .order_by(AnalyticResult.createdAt.desc())
    )

    result = await db.execute(query)
    posts = result.scalars().all()

    # Procesar posts
    processed_posts = []
    sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
    platform_counts = {}
    total_engagement = {"likes": 0, "shares": 0, "comments": 0, "views": 0}

    for post in posts:
        platform = post.source.platform.value if post.source else "unknown"

        post_data = {
            "id": post.id,
            "platform": platform,
            "content": (post.postContent or "")[:300],
            "url": post.postUrl,
            "author": post.postAuthor,
            "date": post.postDate.isoformat() if post.postDate else None,
            "sentiment": post.sentiment,
            "sentiment_score": post.sentimentScore,
            "risk_level": post.riskLevel.value if post.riskLevel else None,
            "risk_score": post.riskScore,
            "topics": post.topics,
            "summary": post.summary,
            "engagement": {
                "likes": post.likes or 0,
                "shares": post.shares or 0,
                "comments": post.comments or 0,
                "views": post.views or 0,
            },
        }

        # Contar por plataforma
        platform_counts[platform] = platform_counts.get(platform, 0) + 1

        # Sumar engagement
        total_engagement["likes"] += post.likes or 0
        total_engagement["shares"] += post.shares or 0
        total_engagement["comments"] += post.comments or 0
        total_engagement["views"] += post.views or 0

        # Contar sentimientos
        sentiment = (post.sentiment or "neutral").lower()
        if "positiv" in sentiment:
            sentiment_counts["positive"] += 1
        elif "negativ" in sentiment:
            sentiment_counts["negative"] += 1
        else:
            sentiment_counts["neutral"] += 1

        processed_posts.append(post_data)

    return {
        "posts": processed_posts,
        "by_platform": platform_counts,
        "sentiment_breakdown": sentiment_counts,
        "engagement_total": total_engagement,
    }


async def _get_analyzed_raw_data_for_period(
    campaign_id: str,
    start_date: datetime,
    end_date: datetime,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Obtiene datos de RawScrapeData analizados por CampaignAnalysis para un período"""

    query = (
        select(CampaignAnalysis)
        .options(selectinload(CampaignAnalysis.raw_data))
        .where(
            CampaignAnalysis.campaignId == campaign_id,
            CampaignAnalysis.analyzedAt >= start_date,
            CampaignAnalysis.analyzedAt <= end_date,
        )
        .order_by(CampaignAnalysis.analyzedAt.desc())
    )

    result = await db.execute(query)
    analyses = result.scalars().all()

    processed_analyses = []
    sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}

    for analysis in analyses:
        raw = analysis.raw_data
        if not raw:
            continue

        analysis_data = {
            "id": analysis.id,
            "raw_id": raw.id,
            "platform": raw.platform,
            "url": raw.postUrl,
            "content": (raw.rawText or "")[:300],
            "date": raw.createdAt.isoformat() if raw.createdAt else None,
            "sentiment_score": analysis.sentimentScore,
            "category": analysis.category.value if analysis.category else None,
            "risk_level": analysis.riskLevel.value if analysis.riskLevel else None,
            "summary": analysis.summary,
            "intent": analysis.intent.value if analysis.intent else None,
            "matched_keywords": analysis.matchedKeywords,
        }

        # Contar sentimientos
        score = analysis.sentimentScore or 0
        if score > 0.3:
            sentiment_counts["positive"] += 1
        elif score < -0.3:
            sentiment_counts["negative"] += 1
        else:
            sentiment_counts["neutral"] += 1

        # Contar riesgos
        risk = (analysis.riskLevel.value if analysis.riskLevel else "bajo").lower()
        if "bajo" in risk:
            risk_counts["low"] += 1
        elif "medio" in risk:
            risk_counts["medium"] += 1
        elif "alto" in risk:
            risk_counts["high"] += 1
        elif "crítico" in risk or "critico" in risk:
            risk_counts["critical"] += 1

        processed_analyses.append(analysis_data)

    return {
        "analyses": processed_analyses,
        "sentiment_breakdown": sentiment_counts,
        "risk_breakdown": risk_counts,
    }


async def _calculate_daily_trend(
    campaign_id: str,
    start_date: date,
    end_date: date,
    db: AsyncSession,
) -> List[Dict[str, Any]]:
    """Calcula la tendencia día a día para el período"""

    trend = []
    current_date = start_date

    while current_date <= end_date:
        day_start = datetime.combine(current_date, datetime.min.time()).replace(tzinfo=timezone.utc)
        day_end = datetime.combine(current_date, datetime.max.time()).replace(tzinfo=timezone.utc)

        # Contar noticias del día
        news_count = await db.execute(
            select(func.count())
            .select_from(IngestedItem)
            .where(
                IngestedItem.campaignId == campaign_id,
                IngestedItem.createdAt >= day_start,
                IngestedItem.createdAt <= day_end,
            )
        )
        news_total = news_count.scalar_one()

        # Contar posts sociales del día
        social_count = await db.execute(
            select(func.count())
            .select_from(AnalyticResult)
            .where(
                AnalyticResult.campaignId == campaign_id,
                AnalyticResult.createdAt >= day_start,
                AnalyticResult.createdAt <= day_end,
            )
        )
        social_total = social_count.scalar_one()

        # Calcular sentimiento promedio del día
        avg_sentiment = await db.execute(
            select(func.avg(Analysis.sentiment))
            .where(
                Analysis.campaignId == campaign_id,
                Analysis.createdAt >= day_start,
                Analysis.createdAt <= day_end,
            )
        )
        avg_sent = avg_sentiment.scalar_one()

        trend.append({
            "date": current_date.isoformat(),
            "news_count": news_total,
            "social_count": social_total,
            "total_mentions": news_total + social_total,
            "avg_sentiment": round(avg_sent, 2) if avg_sent else None,
        })

        current_date += timedelta(days=1)

    return trend


# ============================================================================
# FUNCIONES AUXILIARES - CÁLCULOS Y ANÁLISIS
# ============================================================================
def _calculate_sentiment_summary(
    news_data: Dict[str, Any],
    social_data: Dict[str, Any],
    raw_analyzed_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Calcula el resumen de sentimiento combinado"""

    news_breakdown = news_data["sentiment_breakdown"]
    social_breakdown = social_data["sentiment_breakdown"]
    raw_breakdown = (raw_analyzed_data or {}).get("sentiment_breakdown", {"positive": 0, "negative": 0, "neutral": 0})

    total = {
        "positive": news_breakdown["positive"] + social_breakdown["positive"] + raw_breakdown["positive"],
        "negative": news_breakdown["negative"] + social_breakdown["negative"] + raw_breakdown["negative"],
        "neutral": news_breakdown["neutral"] + social_breakdown["neutral"] + raw_breakdown["neutral"],
    }

    total_count = sum(total.values())

    if total_count == 0:
        return {
            "overall": "neutral",
            "score": 0,
            "breakdown": total,
            "percentages": {"positive": 0, "negative": 0, "neutral": 0},
        }

    # Calcular porcentajes
    percentages = {
        k: round((v / total_count) * 100, 1) for k, v in total.items()
    }

    # Determinar sentimiento predominante
    if total["positive"] > total["negative"] and total["positive"] > total["neutral"]:
        overall = "positive"
        score = (total["positive"] - total["negative"]) / total_count
    elif total["negative"] > total["positive"] and total["negative"] > total["neutral"]:
        overall = "negative"
        score = (total["positive"] - total["negative"]) / total_count
    else:
        overall = "neutral"
        score = 0

    return {
        "overall": overall,
        "score": round(score, 2),
        "breakdown": total,
        "percentages": percentages,
    }


def _calculate_risk_summary(
    social_data: Dict[str, Any],
    raw_analyzed_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Calcula el resumen de riesgo basado en los posts sociales y datos crudos"""

    posts = social_data["posts"]
    raw_analyses = (raw_analyzed_data or {}).get("analyses", [])

    if not posts and not raw_analyses:
        return {
            "level": "low",
            "score": 0,
            "alerts": [],
            "recommendations": [],
        }

    # Contar por nivel de riesgo
    risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    risk_scores = []
    alerts = []

    for post in posts:
        risk_level = post.get("risk_level", "low")
        risk_score = post.get("risk_score", 0)

        if risk_level in risk_counts:
            risk_counts[risk_level] += 1

        if risk_score:
            risk_scores.append(risk_score)

        # Generar alertas para riesgos altos/críticos
        if risk_level in ["high", "critical"]:
            alerts.append({
                "level": risk_level,
                "platform": post.get("platform"),
                "content": post.get("content", "")[:100],
                "url": post.get("url"),
            })

    for analysis in raw_analyses:
        risk_level = (analysis.get("risk_level") or "bajo").lower()
        if "bajo" in risk_level:
            risk_level = "low"
        elif "medio" in risk_level:
            risk_level = "medium"
        elif "alto" in risk_level:
            risk_level = "high"
        elif "crítico" in risk_level or "critico" in risk_level:
            risk_level = "critical"
        
        risk_score = analysis.get("sentiment_score", 0) # Use sentiment as proxy if no explicit score
        
        if risk_level in risk_counts:
            risk_counts[risk_level] += 1
        
        # Generar alertas para riesgos altos/críticos
        if risk_level in ["high", "critical"]:
            alerts.append({
                "level": risk_level,
                "platform": analysis.get("platform"),
                "content": analysis.get("summary", "")[:100],
                "url": analysis.get("url"),
            })

    # Calcular score promedio
    avg_score = sum(risk_scores) / len(risk_scores) if risk_scores else 0

    # Determinar nivel general
    if risk_counts["critical"] > 0:
        overall_level = "critical"
    elif risk_counts["high"] > 2:
        overall_level = "high"
    elif risk_counts["medium"] > 5:
        overall_level = "medium"
    else:
        overall_level = "low"

    # Generar recomendaciones
    recommendations = []
    if overall_level in ["high", "critical"]:
        recommendations.append("Monitorear de cerca las menciones negativas detectadas")
        recommendations.append("Considerar preparar una respuesta o comunicado")

    return {
        "level": overall_level,
        "score": round(avg_score, 1),
        "breakdown": risk_counts,
        "alerts": alerts[:10],  # Máximo 10 alertas
        "recommendations": recommendations,
    }


def _extract_top_topics(
    news_data: Dict[str, Any],
    social_data: Dict[str, Any],
    raw_analyzed_data: Optional[Dict[str, Any]] = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Extrae los temas más mencionados"""

    all_topics = []

    # Topics de noticias
    for item in news_data["items"]:
        topics = item.get("topics") or []
        all_topics.extend(topics)

    # Topics de redes sociales
    for post in social_data["posts"]:
        topics = post.get("topics") or []
        all_topics.extend(topics)

    # Topics de SOCMINT
    if raw_analyzed_data:
        for analysis in raw_analyzed_data["analyses"]:
            topics = analysis.get("matched_keywords") or []
            all_topics.extend(topics)

    # Contar frecuencias
    topic_counts = Counter(all_topics)

    # Retornar top topics
    return [
        {"topic": topic, "count": count}
        for topic, count in topic_counts.most_common(limit)
    ]


def _extract_narratives(social_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extrae las narrativas principales de los posts sociales"""

    narratives = []
    seen = set()

    for post in social_data["posts"]:
        narrative = post.get("summary") or ""
        if narrative and narrative not in seen and len(narrative) > 20:
            seen.add(narrative)
            narratives.append({
                "text": narrative[:200],
                "platform": post.get("platform"),
                "sentiment": post.get("sentiment"),
            })

    return narratives[:10]  # Máximo 10 narrativas


def _calculate_week_comparison(
    current_news: Dict[str, Any],
    current_social: Dict[str, Any],
    current_raw: Dict[str, Any],
    prev_news: Dict[str, Any],
    prev_social: Dict[str, Any],
    prev_raw: Dict[str, Any],
) -> Dict[str, Any]:
    """Calcula la comparativa con la semana anterior"""

    current_total = len(current_news["items"]) + len(current_social["posts"]) + len(current_raw["analyses"])
    prev_total = len(prev_news["items"]) + len(prev_social["posts"]) + len(prev_raw["analyses"])

    # Calcular cambio porcentual
    if prev_total > 0:
        change_pct = ((current_total - prev_total) / prev_total) * 100
    else:
        change_pct = 100 if current_total > 0 else 0

    # Comparar sentimiento
    current_sentiment = _calculate_sentiment_summary(current_news, current_social, current_raw)
    prev_sentiment = _calculate_sentiment_summary(prev_news, prev_social, prev_raw)

    return {
        "mentions": {
            "current": current_total,
            "previous": prev_total,
            "change_pct": round(change_pct, 1),
            "trend": "up" if change_pct > 0 else ("down" if change_pct < 0 else "stable"),
        },
        "news": {
            "current": len(current_news["items"]),
            "previous": len(prev_news["items"]),
        },
        "social": {
            "current": len(current_social["posts"]),
            "previous": len(prev_social["posts"]),
        },
        "socmint": {
            "current": len(current_raw["analyses"]),
            "previous": len(prev_raw["analyses"]),
        },
        "sentiment": {
            "current": current_sentiment["overall"],
            "previous": prev_sentiment["overall"],
            "score_change": round(current_sentiment["score"] - prev_sentiment["score"], 2),
        },
    }


def _generate_insights(
    sentiment: Dict[str, Any],
    comparison: Dict[str, Any],
    risk: Dict[str, Any],
) -> List[str]:
    """Genera insights automáticos basados en los datos"""

    insights = []

    # Insight de menciones
    if comparison["mentions"]["trend"] == "up":
        insights.append(
            f"Las menciones aumentaron {abs(comparison['mentions']['change_pct']):.1f}% respecto a la semana anterior"
        )
    elif comparison["mentions"]["trend"] == "down":
        insights.append(
            f"Las menciones disminuyeron {abs(comparison['mentions']['change_pct']):.1f}% respecto a la semana anterior"
        )

    # Insight de sentimiento
    if sentiment["overall"] == "positive":
        insights.append(
            f"El sentimiento general es positivo ({sentiment['percentages']['positive']}% de las menciones)"
        )
    elif sentiment["overall"] == "negative":
        insights.append(
            f"El sentimiento general es negativo ({sentiment['percentages']['negative']}% de las menciones)"
        )

    # Insight de riesgo
    if risk["level"] in ["high", "critical"]:
        insights.append(
            f"Se detectaron {len(risk['alerts'])} alertas de riesgo que requieren atención"
        )

    return insights


# ============================================================================
# GUARDAR REPORTE EN BD
# ============================================================================
async def save_report(
    campaign_id: str,
    report_type: ReportType,
    report_data: Dict[str, Any],
    db: AsyncSession,
) -> ActorReport:
    """
    Guarda el reporte generado en la base de datos.
    """
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise ValueError(f"Campaña no encontrada: {campaign_id}")

    # Crear resumen corto
    summary = report_data.get("summary", {})
    summary_text = (
        f"{summary.get('total_mentions', 0)} menciones, "
        f"sentimiento {summary.get('sentiment', {}).get('overall', 'neutral')}, "
        f"riesgo {summary.get('risk_level', 'low')}"
    )

    # Crear registro
    report = ActorReport(
        actorName=campaign.query,
        reportType=report_type,
        reportData=report_data,
        summary=summary_text,
        itemCount=summary.get("total_mentions", 0),
    )

    db.add(report)
    await db.commit()
    await db.refresh(report)

    logger.info(f"📝 Reporte guardado: {report.id} ({report_type.value})")

    return report


# ============================================================================
# FUNCIONES DE ALTO NIVEL
# ============================================================================
async def generate_and_save_daily_report(
    campaign_id: str,
    report_date: Optional[date] = None,
    db: AsyncSession = None,
) -> Dict[str, Any]:
    """
    Genera y guarda un reporte diario para una campaña.
    Función de conveniencia para el scheduler.
    """
    if report_date is None:
        report_date = date.today()

    report_data = await generate_daily_report(campaign_id, report_date, db)
    saved_report = await save_report(campaign_id, ReportType.DAILY, report_data, db)

    return {
        "success": True,
        "report_id": saved_report.id,
        "report_type": "daily",
        "campaign_id": campaign_id,
        "report_date": report_date.isoformat(),
    }


async def generate_and_save_weekly_report(
    campaign_id: str,
    week_end_date: Optional[date] = None,
    db: AsyncSession = None,
) -> Dict[str, Any]:
    """
    Genera y guarda un reporte semanal para una campaña.
    Función de conveniencia para el scheduler.
    """
    if week_end_date is None:
        week_end_date = date.today()

    report_data = await generate_weekly_report(campaign_id, week_end_date, db)
    saved_report = await save_report(campaign_id, ReportType.WEEKLY, report_data, db)

    return {
        "success": True,
        "report_id": saved_report.id,
        "report_type": "weekly",
        "campaign_id": campaign_id,
        "week_end_date": week_end_date.isoformat(),
    }
