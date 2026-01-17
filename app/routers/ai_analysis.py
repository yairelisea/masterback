# app/routers/ai_analysis.py
from __future__ import annotations

from fastapi import APIRouter, Query, Header, HTTPException, Request, Depends
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, desc, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from collections import Counter
import time

# Importar el servicio de Perplexity (para analyze-news legacy)
from ..services.perplexity_service import perplexity_service
from ..services.query_builder import build_basic_query
from ..services.apify_service import scrape_news_site, APIFY_AVAILABLE, APIFY_API_TOKEN
from ..db import get_session
from .. import models
from ..models import (
    ActorReport, ReportType, Campaign, AnalyticResult,
    IngestedItem, Analysis, MonitoringSource, SourceLink
)

# Definir el router
router = APIRouter(prefix="/ai", tags=["ai"])

# -----------------------------------------------------------------------------------
# Endpoint principal - Análisis de noticias
# -----------------------------------------------------------------------------------

@router.get("/analyze-news")
async def analyze_news(
    request: Request,
    q: str = Query(..., description="Consulta (ej. nombre del actor político)"),
    size: int = Query(35, ge=1, le=100),
    days_back: int = Query(30, ge=1, le=60),
    lang: str = Query("es-419"),
    country: str = Query("MX"),
    overall: bool = Query(True, description="Si true, devuelve resumen agregado (funcionalidad no disponible con Perplexity)"),
    userId: Optional[str] = None,
    x_user_id: Optional[str] = Header(default=None),
):
    """
    1) Busca y analiza noticias usando el servicio de Perplexity.
    2) Devuelve los resultados analizados.
    """
    effective_user = x_user_id or userId or "anonymous"

    # Calcular fechas para la búsqueda en Perplexity
    end_date_dt = datetime.utcnow()
    start_date_dt = end_date_dt - timedelta(days=days_back)
    
    # Formato de fecha para la API de Perplexity: YYYY-MM-DD
    start_date_str_api = start_date_dt.strftime("%Y-%m-%d")
    end_date_str_api = end_date_dt.strftime("%Y-%m-%d")

    # Formato de fecha para el query string: YYYY-MM-DD
    start_date_str_query = start_date_dt.strftime("%Y-%m-%d")
    end_date_str_query = end_date_dt.strftime("%Y-%m-%d")

    # Construir una consulta más específica
    basic_q = build_basic_query(actor=q, campaign_name=q, city_keywords=[country])

    # Añadir filtros de fecha a la consulta
    q_with_dates = f"{basic_q} after:{start_date_str_query} before:{end_date_str_query}"

    try:
        # Llamar al servicio de Perplexity
        analyzed_articles = await perplexity_service.search_and_analyze(
            query=q_with_dates,
            campaign_name=q,
            start_date=start_date_str_api,
            end_date=end_date_str_api,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el servicio de Perplexity: {e}")

    if not analyzed_articles:
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

    # El servicio de Perplexity ya devuelve los items analizados.
    overall_block = {
        "summary": "El resumen general no está disponible en esta versión.",
        "sentiment_label": None,
        "sentiment_score": None,
        "topics": [],
        "perception": {},
    }

    return {
        "overall": overall_block,
        "items": analyzed_articles,
        "meta": {
            "q": q,
            "size": size,
            "days_back": days_back,
            "lang": lang,
            "country": country,
            "user": effective_user,
        },
    }


# -----------------------------------------------------------------------------------
# Endpoint: Diagnóstico de Apify
# -----------------------------------------------------------------------------------

@router.get("/apify-status")
async def get_apify_status(
    db: AsyncSession = Depends(get_session)
):
    """
    Endpoint de diagnóstico para verificar la configuración de Apify.
    """
    import os

    # Verificar configuración
    token_configured = bool(APIFY_API_TOKEN)
    token_preview = f"{APIFY_API_TOKEN[:8]}...{APIFY_API_TOKEN[-4:]}" if APIFY_API_TOKEN and len(APIFY_API_TOKEN) > 12 else "NO CONFIGURADO"

    # Contar SourceLinks en la BD (tabla source_links)
    source_links_count = await db.execute(select(func.count(SourceLink.id)))
    total_source_links = source_links_count.scalar() or 0

    # Contar MonitoringSource en la BD (tabla monitoring_sources - usada por el frontend)
    monitoring_sources_count = await db.execute(select(func.count(MonitoringSource.id)))
    total_monitoring_sources = monitoring_sources_count.scalar() or 0

    total_sources = total_source_links + total_monitoring_sources

    # Obtener ejemplo de SourceLinks
    sample_source_links = await db.execute(select(SourceLink).limit(3))
    source_links_sample = [{"url": sl.url, "type": sl.type.value if sl.type else None, "campaignId": sl.campaignId, "tabla": "source_links"} for sl in sample_source_links.scalars().all()]

    # Obtener ejemplo de MonitoringSources
    sample_monitoring = await db.execute(select(MonitoringSource).limit(3))
    monitoring_sample = [{"url": ms.url, "platform": ms.platform, "campaignId": ms.campaignId, "tabla": "monitoring_sources"} for ms in sample_monitoring.scalars().all()]

    return {
        "apify_client_available": APIFY_AVAILABLE,
        "apify_token_configured": token_configured,
        "apify_token_preview": token_preview,
        "total_sources": total_sources,
        "source_links_count": total_source_links,
        "monitoring_sources_count": total_monitoring_sources,
        "sources_sample": source_links_sample + monitoring_sample,
        "env_check": {
            "APIFY_API_TOKEN": "SET" if os.getenv("APIFY_API_TOKEN") else "NOT SET",
            "PERPLEXITY_API_KEY": "SET" if os.getenv("PERPLEXITY_API_KEY") else "NOT SET",
        },
        "recommendations": []
        if (APIFY_AVAILABLE and token_configured and total_sources > 0)
        else [
            "Instalar apify-client: pip install apify-client" if not APIFY_AVAILABLE else None,
            "Configurar APIFY_API_TOKEN en variables de entorno" if not token_configured else None,
            "Agregar fuentes desde el panel de admin (Fuentes de Monitoreo)" if total_sources == 0 else None,
        ]
    }


# -----------------------------------------------------------------------------------
# Endpoint: Reporte Semanal con guardado en BD
# Usa datos de MonitoringSources + Análisis con Perplexity
# -----------------------------------------------------------------------------------

@router.get("/weekly-report")
async def get_weekly_report(
    q: str = Query(..., description="Nombre del actor político o query de campaña"),
    force_refresh: bool = Query(False, description="Forzar regeneración aunque exista cache"),
    db: AsyncSession = Depends(get_session)
):
    """
    Genera un reporte semanal:
    1. Recopila datos de MonitoringSources (redes sociales) e IngestedItems (noticias)
    2. Envía los datos a Perplexity para análisis inteligente
    3. Combina métricas locales con análisis de IA
    """
    try:
        start_time = time.time()

        # 1. Buscar la campaña por query, name o id (flexible)
        campaign_query = select(Campaign).where(
            or_(
                Campaign.query == q,
                Campaign.name == q,
                Campaign.id == q,
                Campaign.query.ilike(f"%{q}%"),
                Campaign.name.ilike(f"%{q}%"),
            )
        )
        result = await db.execute(campaign_query)
        campaign = result.scalars().first()

        if not campaign:
            # Si no hay campaña, usar Perplexity directamente (fallback)
            print(f"⚠️ No hay campaña para '{q}', usando Perplexity directo")
            weekly_report_data = await perplexity_service.get_weekly_actor_report(actor_name=q)
            if isinstance(weekly_report_data, dict):
                return {
                    **weekly_report_data,
                    "_metadata": {"from_cache": False, "campaign_found": False, "source": "perplexity_only"}
                }
            return {"error": "No se pudo generar el reporte"}

        # 2. Buscar reporte reciente en cache (< 6 horas)
        if not force_refresh:
            cache_query = select(ActorReport).where(
                ActorReport.actorName == q,
                ActorReport.reportType == ReportType.WEEKLY,
                ActorReport.createdAt > datetime.utcnow() - timedelta(hours=6)
            ).order_by(desc(ActorReport.createdAt))

            cache_result = await db.execute(cache_query)
            cached_report = cache_result.scalars().first()

            if cached_report:
                print(f"📦 Reporte semanal de '{q}' encontrado en cache")
                return {
                    **cached_report.reportData,
                    "_metadata": {
                        "from_cache": True,
                        "generated_at": cached_report.createdAt.isoformat(),
                        "report_id": cached_report.id
                    }
                }

        # 3. Recopilar datos locales
        print(f"🔄 Generando reporte semanal para '{q}' (campaña: {campaign.id})")

        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)

        # Debug: ver cuántos datos hay en total para esta campaña
        total_social_query = select(func.count()).select_from(AnalyticResult).where(AnalyticResult.campaignId == campaign.id)
        total_social = (await db.execute(total_social_query)).scalar()

        total_news_query = select(func.count()).select_from(IngestedItem).where(IngestedItem.campaignId == campaign.id)
        total_news = (await db.execute(total_news_query)).scalar()

        print(f"📊 Total datos en BD para campaña {campaign.id}: {total_social} social, {total_news} noticias")

        # 3a. Obtener datos de redes sociales (AnalyticResult) - sin filtro de fecha ni isRelevant para debug
        social_query = (
            select(AnalyticResult)
            .options(selectinload(AnalyticResult.source))
            .where(
                AnalyticResult.campaignId == campaign.id,
            )
            .order_by(desc(AnalyticResult.createdAt))
            .limit(100)
        )
        social_result = await db.execute(social_query)
        social_posts = social_result.scalars().all()

        print(f"📱 Posts de redes sociales obtenidos: {len(social_posts)}")

        # 3b. Obtener datos de noticias (IngestedItem + Analysis) - sin filtro de fecha para debug
        news_query = (
            select(IngestedItem)
            .options(selectinload(IngestedItem.analysis))
            .where(
                IngestedItem.campaignId == campaign.id,
            )
            .order_by(desc(IngestedItem.createdAt))
            .limit(100)
        )
        news_result = await db.execute(news_query)
        news_items = news_result.scalars().all()

        print(f"📰 Noticias obtenidas: {len(news_items)}")

        # 4. Procesar métricas locales
        sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
        risk_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        all_topics = []
        platform_counts = {}
        total_engagement = {"likes": 0, "shares": 0, "comments": 0, "views": 0}

        # Preparar contenido para enviar a Perplexity
        contenido_para_analisis = []
        log_evidencia = []

        for post in social_posts:
            platform = post.source.platform.value if post.source else "unknown"
            platform_counts[platform] = platform_counts.get(platform, 0) + 1

            sentiment = (post.sentiment or "neutral").lower()
            if "positiv" in sentiment:
                sentiment_counts["positive"] += 1
            elif "negativ" in sentiment:
                sentiment_counts["negative"] += 1
            else:
                sentiment_counts["neutral"] += 1

            risk = post.riskLevel.value if post.riskLevel else "low"
            if risk in risk_counts:
                risk_counts[risk] += 1

            if post.topics:
                all_topics.extend(post.topics)

            total_engagement["likes"] += post.likes or 0
            total_engagement["shares"] += post.shares or 0
            total_engagement["comments"] += post.comments or 0
            total_engagement["views"] += post.views or 0

            # Contenido para Perplexity
            contenido_para_analisis.append({
                "tipo": "red_social",
                "plataforma": platform,
                "contenido": (post.postContent or "")[:300],
                "autor": post.postAuthor,
                "fecha": post.postDate.strftime("%Y-%m-%d") if post.postDate else None,
                "sentimiento_previo": post.sentiment,
                "engagement": post.likes or 0 + (post.shares or 0) + (post.comments or 0)
            })

            log_evidencia.append({
                "descripcion": post.summary or (post.postContent or "")[:200],
                "fecha": post.postDate.strftime("%Y-%m-%d") if post.postDate else post.createdAt.strftime("%Y-%m-%d"),
                "tipo_medio": f"Redes Sociales - {platform.title()}",
                "link": post.postUrl or "",
                "plataforma": platform,
                "autor": post.postAuthor,
                "sentimiento": post.sentiment,
                "engagement": {"likes": post.likes or 0, "shares": post.shares or 0, "comments": post.comments or 0}
            })

        for item in news_items:
            if item.analysis:
                tone = (item.analysis.tone or "neutral").lower()
                if "positiv" in tone:
                    sentiment_counts["positive"] += 1
                elif "negativ" in tone:
                    sentiment_counts["negative"] += 1
                else:
                    sentiment_counts["neutral"] += 1
                if item.analysis.topics:
                    all_topics.extend(item.analysis.topics)

            contenido_para_analisis.append({
                "tipo": "noticia",
                "titulo": item.title,
                "url": item.url,
                "fecha": item.publishedAt.strftime("%Y-%m-%d") if item.publishedAt else None,
                "resumen": item.analysis.summary if item.analysis else None,
                "sentimiento_previo": item.analysis.tone if item.analysis else None
            })

            log_evidencia.append({
                "descripcion": item.analysis.summary if item.analysis else item.title,
                "fecha": item.publishedAt.strftime("%Y-%m-%d") if item.publishedAt else item.createdAt.strftime("%Y-%m-%d"),
                "tipo_medio": "Noticias",
                "link": item.url or "",
                "titulo": item.title,
                "sentimiento": item.analysis.tone if item.analysis else None,
            })

        total_menciones = len(social_posts) + len(news_items)
        topic_counts = Counter(all_topics)
        top_topics = [{"tema": t, "menciones": c} for t, c in topic_counts.most_common(10)]

        # Si no hay datos locales, buscar fuentes de la campaña y usar Apify para scraping
        if total_menciones == 0:
            print(f"⚠️ No hay datos locales para '{q}', buscando fuentes configuradas...")

            # Obtener las fuentes (URLs) configuradas para esta campaña
            # 1. Primero buscar en SourceLink (tabla source_links)
            source_links_query = select(SourceLink).where(SourceLink.campaignId == campaign.id)
            source_links_result = await db.execute(source_links_query)
            source_links = source_links_result.scalars().all()

            # 2. También buscar en MonitoringSource (tabla monitoring_sources - usada por el frontend)
            monitoring_sources_query = select(MonitoringSource).where(MonitoringSource.campaignId == campaign.id)
            monitoring_sources_result = await db.execute(monitoring_sources_query)
            monitoring_sources = monitoring_sources_result.scalars().all()

            # Combinar ambas fuentes en una lista unificada
            all_source_urls = []
            for sl in source_links:
                all_source_urls.append({"url": sl.url, "source": "source_links"})
            for ms in monitoring_sources:
                all_source_urls.append({"url": ms.url, "source": "monitoring_sources"})

            print(f"📎 Fuentes encontradas: {len(source_links)} SourceLinks + {len(monitoring_sources)} MonitoringSources = {len(all_source_urls)} total")

            actor_name = campaign.query or campaign.name or q
            scraped_articles = []

            if all_source_urls and APIFY_AVAILABLE:
                # Usar Apify para hacer scraping de cada fuente
                print(f"🔗 Usando Apify para scraping de {len(all_source_urls)} fuentes...")

                for src in all_source_urls:
                    try:
                        print(f"📰 Scraping: {src['url']} (de {src['source']})")
                        articles = await scrape_news_site(
                            site_url=src['url'],
                            candidate_name=actor_name,
                            max_posts=20,
                            days_back=7
                        )
                        if articles:
                            scraped_articles.extend(articles)
                            print(f"   ✅ {len(articles)} artículos encontrados mencionando a '{actor_name}'")
                        else:
                            print(f"   ⚠️ No se encontraron artículos relevantes")
                    except Exception as e:
                        print(f"   ❌ Error en scraping de {src['url']}: {e}")
                        continue

                print(f"📊 Total artículos scrapeados: {len(scraped_articles)}")

                if scraped_articles:
                    # Convertir artículos scrapeados a formato de evidencia
                    for art in scraped_articles:
                        log_evidencia.append({
                            "descripcion": art.get("title") or art.get("content", "")[:200],
                            "fecha": art.get("date") or now.strftime("%Y-%m-%d"),
                            "tipo_medio": f"Noticias - {art.get('source_name', 'Fuente configurada')}",
                            "link": art.get("url", ""),
                            "titulo": art.get("title"),
                            "sentimiento": None,  # Se analizará con Perplexity
                            "fuente": art.get("source_name"),
                            "region": art.get("source_region"),
                        })
                        contenido_para_analisis.append({
                            "tipo": "noticia_scrapeada",
                            "titulo": art.get("title"),
                            "url": art.get("url"),
                            "contenido": art.get("content", "")[:500],
                            "fuente": art.get("source_name"),
                        })

                    total_menciones = len(scraped_articles)
                    source_type = "apify_scraping"
                    note = f"Scraping con Apify de {len(all_source_urls)} fuentes: {len(scraped_articles)} artículos"

                    # Enviar contenido scrapeado a Perplexity para análisis
                    print(f"🤖 Enviando {len(contenido_para_analisis)} artículos scrapeados a Perplexity...")
                    try:
                        analisis_ia = await perplexity_service.analyze_collected_data(
                            actor_name=actor_name,
                            data=contenido_para_analisis[:30],
                            metricas={
                                "total": total_menciones,
                                "fuentes_scrapeadas": len(all_source_urls),
                                "articulos_encontrados": len(scraped_articles),
                            }
                        )
                    except Exception as e:
                        print(f"⚠️ Error en Perplexity: {e}")
                        analisis_ia = {
                            "resumen_ejecutivo": f"Se encontraron {len(scraped_articles)} artículos sobre {actor_name} en las fuentes configuradas.",
                            "analisis_estrategico": "Análisis pendiente.",
                            "recomendaciones": []
                        }

                    # Construir reporte con datos scrapeados
                    weekly_report_data = {
                        "resumen_ejecutivo": analisis_ia.get("resumen_ejecutivo", f"Análisis semanal de {actor_name}"),
                        "analisis_estrategico": analisis_ia.get("analisis_estrategico", ""),
                        "recomendaciones": analisis_ia.get("recomendaciones", []),
                        "log_de_evidencia": log_evidencia[:50],
                        "metricas": {
                            "total_menciones": total_menciones,
                            "fuentes_analizadas": len(all_source_urls),
                            "articulos_encontrados": len(scraped_articles),
                        },
                        "periodo": {
                            "inicio": week_ago.strftime("%Y-%m-%d"),
                            "fin": now.strftime("%Y-%m-%d"),
                        }
                    }
                else:
                    # Apify no encontró artículos relevantes, usar Perplexity como fallback
                    print(f"⚠️ Apify no encontró artículos, usando Perplexity búsqueda web")
                    weekly_report_data = await perplexity_service.get_weekly_actor_report(actor_name=actor_name)
                    source_type = "perplexity_fallback"
                    note = f"Apify no encontró menciones de '{actor_name}' en las fuentes. Se usó búsqueda web."

            elif all_source_urls and not APIFY_AVAILABLE:
                # Apify no está disponible, usar Perplexity directamente
                print(f"⚠️ Apify no disponible, usando Perplexity búsqueda web")
                weekly_report_data = await perplexity_service.get_weekly_actor_report(actor_name=actor_name)
                source_type = "perplexity_no_apify"
                note = "Apify no está configurado. Se usó búsqueda web de Perplexity."
            else:
                # Si no hay fuentes configuradas, usar búsqueda web general
                print(f"⚠️ No hay fuentes configuradas, usando Perplexity búsqueda web")
                weekly_report_data = await perplexity_service.get_weekly_actor_report(actor_name=actor_name)
                source_type = "perplexity_web_search"
                note = "No hay datos de monitoreo local ni fuentes configuradas, se usó búsqueda web"

            if isinstance(weekly_report_data, dict):
                # Guardar en BD
                generation_time = time.time() - start_time
                new_report = ActorReport(
                    actorName=q,
                    reportType=ReportType.WEEKLY,
                    reportData=weekly_report_data,
                    summary=(weekly_report_data.get("resumen_ejecutivo", {}).get("sintesis", "") or "")[:500] if isinstance(weekly_report_data.get("resumen_ejecutivo"), dict) else str(weekly_report_data.get("resumen_ejecutivo", ""))[:500],
                    generationTime=generation_time,
                    itemCount=total_menciones if total_menciones > 0 else len(all_source_urls)
                )
                db.add(new_report)
                await db.commit()
                await db.refresh(new_report)

                return {
                    **weekly_report_data,
                    "_metadata": {
                        "from_cache": False,
                        "generated_at": new_report.createdAt.isoformat(),
                        "report_id": new_report.id,
                        "campaign_id": campaign.id,
                        "source": source_type,
                        "sources_count": len(all_source_urls),
                        "articles_found": len(scraped_articles) if scraped_articles else 0,
                        "note": note
                    }
                }
            return {"error": "No se pudo generar el reporte"}

        max_sentiment = max(sentiment_counts, key=sentiment_counts.get) if total_menciones > 0 else "neutral"
        sentiment_pct = {
            k: round((v / total_menciones) * 100, 1) if total_menciones > 0 else 0
            for k, v in sentiment_counts.items()
        }

        if risk_counts["critical"] > 0:
            risk_level = "CRÍTICO"
        elif risk_counts["high"] > 2:
            risk_level = "ALTO"
        elif risk_counts["medium"] > 5:
            risk_level = "MEDIO"
        else:
            risk_level = "BAJO"

        # 5. Enviar a Perplexity para análisis inteligente
        print(f"🤖 Enviando {len(contenido_para_analisis)} items a Perplexity para análisis...")

        try:
            analisis_ia = await perplexity_service.analyze_collected_data(
                actor_name=q,
                data=contenido_para_analisis[:30],  # Limitar para no exceder tokens
                metricas={
                    "total": total_menciones,
                    "redes": len(social_posts),
                    "noticias": len(news_items),
                    "sentimiento": sentiment_counts,
                    "riesgo": risk_counts,
                    "engagement": total_engagement,
                    "plataformas": platform_counts,
                    "temas": [t["tema"] for t in top_topics[:5]]
                }
            )
        except Exception as e:
            print(f"⚠️ Error en Perplexity, usando resumen local: {e}")
            analisis_ia = {
                "resumen_ejecutivo": f"Análisis de {q}: {total_menciones} menciones en la última semana.",
                "analisis_estrategico": f"Sentimiento predominante: {max_sentiment}. Nivel de riesgo: {risk_level}.",
                "recomendaciones": ["Continuar monitoreo de fuentes configuradas."]
            }

        # 6. Construir reporte final combinando datos locales + IA
        weekly_report_data = {
            "resumen_ejecutivo": analisis_ia.get("resumen_ejecutivo", f"Análisis semanal de {q}"),
            "analisis_estrategico": analisis_ia.get("analisis_estrategico", ""),
            "recomendaciones": analisis_ia.get("recomendaciones", []),
            "log_de_evidencia": log_evidencia[:50],
            "metricas": {
                "total_menciones": total_menciones,
                "menciones_redes": len(social_posts),
                "menciones_noticias": len(news_items),
                "sentimiento": sentiment_counts,
                "sentimiento_porcentaje": sentiment_pct,
                "sentimiento_predominante": max_sentiment,
                "riesgo": risk_counts,
                "nivel_riesgo": risk_level,
                "engagement": total_engagement,
                "plataformas": platform_counts,
            },
            "temas_principales": top_topics,
            "periodo": {
                "inicio": week_ago.strftime("%Y-%m-%d"),
                "fin": now.strftime("%Y-%m-%d"),
            }
        }

        generation_time = time.time() - start_time

        # 7. Guardar en BD
        new_report = ActorReport(
            actorName=q,
            reportType=ReportType.WEEKLY,
            reportData=weekly_report_data,
            summary=(analisis_ia.get("resumen_ejecutivo", "") or "")[:500],
            generationTime=generation_time,
            itemCount=total_menciones
        )

        db.add(new_report)
        await db.commit()
        await db.refresh(new_report)

        print(f"✅ Reporte semanal guardado (ID: {new_report.id}) - {total_menciones} menciones")

        return {
            **weekly_report_data,
            "_metadata": {
                "from_cache": False,
                "generated_at": new_report.createdAt.isoformat(),
                "report_id": new_report.id,
                "generation_time": round(generation_time, 2),
                "campaign_id": campaign.id,
                "sources_count": len(platform_counts),
                "analyzed_by": "perplexity"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error al generar reporte semanal: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error al generar el reporte semanal: {e}")


# -----------------------------------------------------------------------------------
# Endpoint: Resumen Diario con guardado en BD
# Usa datos de MonitoringSources + Análisis con Perplexity
# -----------------------------------------------------------------------------------

@router.get("/daily-summary")
async def get_daily_summary(
    q: str = Query(..., description="Nombre del actor político o query de campaña"),
    force_refresh: bool = Query(False, description="Forzar regeneración aunque exista cache"),
    db: AsyncSession = Depends(get_session)
):
    """
    Genera un resumen diario:
    1. Recopila datos de las últimas 24 horas de MonitoringSources e IngestedItems
    2. Envía los datos a Perplexity para análisis
    3. Combina métricas locales con análisis de IA
    """
    try:
        start_time = time.time()

        # 1. Buscar la campaña por query, name o id (flexible)
        campaign_query = select(Campaign).where(
            or_(
                Campaign.query == q,
                Campaign.name == q,
                Campaign.id == q,
                Campaign.query.ilike(f"%{q}%"),
                Campaign.name.ilike(f"%{q}%"),
            )
        )
        result = await db.execute(campaign_query)
        campaign = result.scalars().first()

        if not campaign:
            # Si no hay campaña, usar Perplexity directamente (fallback)
            print(f"⚠️ No hay campaña para '{q}', usando Perplexity directo")
            daily_data = await perplexity_service.get_daily_actor_summary(actor_name=q)
            if isinstance(daily_data, dict):
                return {
                    **daily_data,
                    "_metadata": {"from_cache": False, "campaign_found": False, "source": "perplexity_only"}
                }
            return {"error": "No se pudo generar el resumen"}

        # 2. Buscar reporte reciente en cache (< 3 horas)
        if not force_refresh:
            cache_query = select(ActorReport).where(
                ActorReport.actorName == q,
                ActorReport.reportType == ReportType.DAILY,
                ActorReport.createdAt > datetime.now(timezone.utc) - timedelta(hours=3)
            ).order_by(desc(ActorReport.createdAt))

            cache_result = await db.execute(cache_query)
            cached_report = cache_result.scalars().first()

            if cached_report:
                print(f"📦 Resumen diario de '{q}' encontrado en cache")
                return {
                    **cached_report.reportData,
                    "_metadata": {
                        "from_cache": True,
                        "generated_at": cached_report.createdAt.isoformat(),
                        "report_id": cached_report.id
                    }
                }

        # 3. Recopilar datos de las últimas 24 horas
        print(f"🔄 Generando resumen diario para '{q}' (campaña: {campaign.id})")

        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(hours=24)

        # 3a. Obtener datos de redes sociales
        social_query = (
            select(AnalyticResult)
            .options(selectinload(AnalyticResult.source))
            .where(
                AnalyticResult.campaignId == campaign.id,
                AnalyticResult.createdAt >= yesterday,
                AnalyticResult.isRelevant == True,
            )
            .order_by(desc(AnalyticResult.createdAt))
            .limit(50)
        )
        social_result = await db.execute(social_query)
        social_posts = social_result.scalars().all()

        # 3b. Obtener noticias
        news_query = (
            select(IngestedItem)
            .options(selectinload(IngestedItem.analysis))
            .where(
                IngestedItem.campaignId == campaign.id,
                IngestedItem.createdAt >= yesterday,
            )
            .order_by(desc(IngestedItem.createdAt))
            .limit(50)
        )
        news_result = await db.execute(news_query)
        news_items = news_result.scalars().all()

        # 4. Procesar métricas
        sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
        all_topics = []
        platform_counts = {}
        total_engagement = {"likes": 0, "shares": 0, "comments": 0}

        contenido_para_analisis = []
        registro_evidencia = []

        for post in social_posts:
            platform = post.source.platform.value if post.source else "unknown"
            platform_counts[platform] = platform_counts.get(platform, 0) + 1

            sentiment = (post.sentiment or "neutral").lower()
            if "positiv" in sentiment:
                sentiment_counts["positive"] += 1
            elif "negativ" in sentiment:
                sentiment_counts["negative"] += 1
            else:
                sentiment_counts["neutral"] += 1

            if post.topics:
                all_topics.extend(post.topics)

            total_engagement["likes"] += post.likes or 0
            total_engagement["shares"] += post.shares or 0
            total_engagement["comments"] += post.comments or 0

            contenido_para_analisis.append({
                "tipo": "red_social",
                "plataforma": platform,
                "contenido": (post.postContent or "")[:200],
                "autor": post.postAuthor,
                "sentimiento_previo": post.sentiment,
            })

            registro_evidencia.append({
                "descripcion": post.summary or (post.postContent or "")[:150],
                "fecha": post.postDate.strftime("%Y-%m-%d %H:%M") if post.postDate else "Hoy",
                "tipo_medio": platform.title(),
                "link": post.postUrl or "",
                "autor": post.postAuthor,
                "sentimiento": post.sentiment,
            })

        for item in news_items:
            if item.analysis:
                tone = (item.analysis.tone or "neutral").lower()
                if "positiv" in tone:
                    sentiment_counts["positive"] += 1
                elif "negativ" in tone:
                    sentiment_counts["negative"] += 1
                else:
                    sentiment_counts["neutral"] += 1
                if item.analysis.topics:
                    all_topics.extend(item.analysis.topics)

            contenido_para_analisis.append({
                "tipo": "noticia",
                "titulo": item.title,
                "resumen": item.analysis.summary if item.analysis else None,
            })

            registro_evidencia.append({
                "descripcion": item.analysis.summary if item.analysis else item.title,
                "fecha": item.publishedAt.strftime("%Y-%m-%d") if item.publishedAt else "Hoy",
                "tipo_medio": "Noticia",
                "link": item.url or "",
                "sentimiento": item.analysis.tone if item.analysis else None,
            })

        total_menciones = len(social_posts) + len(news_items)
        topic_counts = Counter(all_topics)
        top_topics = [t for t, _ in topic_counts.most_common(5)]

        # Si no hay datos locales, buscar fuentes de la campaña y usar Apify para scraping
        if total_menciones == 0:
            print(f"⚠️ No hay datos locales para '{q}', buscando fuentes configuradas...")

            # Obtener las fuentes (URLs) configuradas para esta campaña
            # 1. Primero buscar en SourceLink (tabla source_links)
            source_links_query = select(SourceLink).where(SourceLink.campaignId == campaign.id)
            source_links_result = await db.execute(source_links_query)
            source_links = source_links_result.scalars().all()

            # 2. También buscar en MonitoringSource (tabla monitoring_sources - usada por el frontend)
            monitoring_sources_query = select(MonitoringSource).where(MonitoringSource.campaignId == campaign.id)
            monitoring_sources_result = await db.execute(monitoring_sources_query)
            monitoring_sources = monitoring_sources_result.scalars().all()

            # Combinar ambas fuentes en una lista unificada
            all_source_urls = []
            for sl in source_links:
                all_source_urls.append({"url": sl.url, "source": "source_links"})
            for ms in monitoring_sources:
                all_source_urls.append({"url": ms.url, "source": "monitoring_sources"})

            print(f"📎 Fuentes encontradas: {len(source_links)} SourceLinks + {len(monitoring_sources)} MonitoringSources = {len(all_source_urls)} total")

            actor_name = campaign.query or campaign.name or q
            scraped_articles = []

            if all_source_urls and APIFY_AVAILABLE:
                # Usar Apify para hacer scraping de cada fuente
                print(f"🔗 Usando Apify para scraping diario de {len(all_source_urls)} fuentes...")

                for src in all_source_urls:
                    try:
                        print(f"📰 Scraping: {src['url']} (de {src['source']})")
                        articles = await scrape_news_site(
                            site_url=src['url'],
                            candidate_name=actor_name,
                            max_posts=10,
                            days_back=1  # Solo últimas 24 horas para reporte diario
                        )
                        if articles:
                            scraped_articles.extend(articles)
                            print(f"   ✅ {len(articles)} artículos encontrados")
                        else:
                            print(f"   ⚠️ No se encontraron artículos relevantes")
                    except Exception as e:
                        print(f"   ❌ Error en scraping de {src['url']}: {e}")
                        continue

                print(f"📊 Total artículos scrapeados: {len(scraped_articles)}")

                if scraped_articles:
                    # Convertir artículos scrapeados a formato de evidencia
                    for art in scraped_articles:
                        registro_evidencia.append({
                            "descripcion": art.get("title") or art.get("content", "")[:200],
                            "fecha": art.get("date") or now.strftime("%Y-%m-%d"),
                            "tipo_medio": f"Noticias - {art.get('source_name', 'Fuente configurada')}",
                            "link": art.get("url", ""),
                            "titulo": art.get("title"),
                            "sentimiento": None,
                            "fuente": art.get("source_name"),
                        })
                        contenido_para_analisis.append({
                            "tipo": "noticia_scrapeada",
                            "titulo": art.get("title"),
                            "url": art.get("url"),
                            "contenido": art.get("content", "")[:300],
                            "fuente": art.get("source_name"),
                        })

                    total_menciones = len(scraped_articles)
                    source_type = "apify_scraping"
                    note = f"Scraping con Apify de {len(all_source_urls)} fuentes: {len(scraped_articles)} artículos"

                    # Enviar contenido scrapeado a Perplexity para análisis
                    print(f"🤖 Enviando {len(contenido_para_analisis)} artículos a Perplexity...")
                    try:
                        analisis_ia = await perplexity_service.analyze_collected_data(
                            actor_name=actor_name,
                            data=contenido_para_analisis[:20],
                            metricas={
                                "total": total_menciones,
                                "fuentes_scrapeadas": len(all_source_urls),
                                "articulos_encontrados": len(scraped_articles),
                            }
                        )
                    except Exception as e:
                        print(f"⚠️ Error en Perplexity: {e}")
                        analisis_ia = {
                            "resumen_ejecutivo": f"Se encontraron {len(scraped_articles)} artículos sobre {actor_name} hoy.",
                            "analisis_estrategico": "Análisis pendiente.",
                            "recomendaciones": []
                        }

                    # Construir reporte diario con datos scrapeados
                    daily_data = {
                        "resumen_diario_express": analisis_ia.get("resumen_ejecutivo", f"Resumen diario de {actor_name}"),
                        "analisis_del_dia": analisis_ia.get("analisis_estrategico", ""),
                        "recomendaciones": analisis_ia.get("recomendaciones", []),
                        "registro_de_evidencia": registro_evidencia[:30],
                        "metricas": {
                            "total_menciones": total_menciones,
                            "fuentes_analizadas": len(all_source_urls),
                            "articulos_encontrados": len(scraped_articles),
                        },
                        "periodo": {
                            "inicio": yesterday.strftime("%Y-%m-%d %H:%M"),
                            "fin": now.strftime("%Y-%m-%d %H:%M"),
                        }
                    }
                else:
                    # Apify no encontró artículos relevantes, usar Perplexity como fallback
                    print(f"⚠️ Apify no encontró artículos, usando Perplexity búsqueda web")
                    daily_data = await perplexity_service.get_daily_actor_summary(actor_name=actor_name)
                    source_type = "perplexity_fallback"
                    note = f"Apify no encontró menciones de '{actor_name}' en las fuentes. Se usó búsqueda web."

            elif all_source_urls and not APIFY_AVAILABLE:
                # Apify no está disponible, usar Perplexity directamente
                print(f"⚠️ Apify no disponible, usando Perplexity búsqueda web")
                daily_data = await perplexity_service.get_daily_actor_summary(actor_name=actor_name)
                source_type = "perplexity_no_apify"
                note = "Apify no está configurado. Se usó búsqueda web de Perplexity."
            else:
                # Si no hay fuentes configuradas, usar búsqueda web general
                print(f"⚠️ No hay fuentes configuradas, usando Perplexity búsqueda web")
                daily_data = await perplexity_service.get_daily_actor_summary(actor_name=actor_name)
                source_type = "perplexity_web_search"
                note = "No hay datos de monitoreo local ni fuentes configuradas, se usó búsqueda web"

            if isinstance(daily_data, dict):
                # Guardar en BD
                generation_time = time.time() - start_time
                new_report = ActorReport(
                    actorName=q,
                    reportType=ReportType.DAILY,
                    reportData=daily_data,
                    summary=str(daily_data.get("resumen_diario_express", ""))[:500],
                    generationTime=generation_time,
                    itemCount=total_menciones if total_menciones > 0 else len(all_source_urls)
                )
                db.add(new_report)
                await db.commit()
                await db.refresh(new_report)

                return {
                    **daily_data,
                    "_metadata": {
                        "from_cache": False,
                        "generated_at": new_report.createdAt.isoformat(),
                        "report_id": new_report.id,
                        "campaign_id": campaign.id,
                        "source": source_type,
                        "sources_count": len(all_source_urls),
                        "articles_found": len(scraped_articles) if scraped_articles else 0,
                        "note": note
                    }
                }
            return {"error": "No se pudo generar el resumen"}

        max_sentiment = max(sentiment_counts, key=sentiment_counts.get) if total_menciones > 0 else "neutral"

        # 5. Enviar a Perplexity para análisis
        print(f"🤖 Enviando {len(contenido_para_analisis)} items a Perplexity...")

        try:
            analisis_ia = await perplexity_service.analyze_collected_data(
                actor_name=q,
                data=contenido_para_analisis[:20],
                metricas={
                    "total": total_menciones,
                    "redes": len(social_posts),
                    "noticias": len(news_items),
                    "sentimiento": sentiment_counts,
                    "engagement": total_engagement,
                    "plataformas": platform_counts,
                    "temas": top_topics
                }
            )
        except Exception as e:
            print(f"⚠️ Error en Perplexity: {e}")
            analisis_ia = {
                "resumen_ejecutivo": f"Resumen del día para {q}: {total_menciones} menciones detectadas.",
                "analisis_estrategico": f"Sentimiento predominante: {max_sentiment}.",
                "recomendaciones": []
            }

        # 6. Construir respuesta
        daily_summary_data = {
            "resumen_diario_express": analisis_ia.get("resumen_ejecutivo", f"Resumen diario de {q}"),
            "analisis_del_dia": analisis_ia.get("analisis_estrategico", ""),
            "recomendaciones": analisis_ia.get("recomendaciones", []),
            "registro_de_evidencia": registro_evidencia[:30],
            "metricas": {
                "total_menciones": total_menciones,
                "menciones_redes": len(social_posts),
                "menciones_noticias": len(news_items),
                "sentimiento": sentiment_counts,
                "sentimiento_predominante": max_sentiment,
                "engagement": total_engagement,
                "plataformas": platform_counts,
            },
            "temas_del_dia": top_topics,
            "periodo": {
                "inicio": yesterday.strftime("%Y-%m-%d %H:%M"),
                "fin": now.strftime("%Y-%m-%d %H:%M"),
            }
        }

        generation_time = time.time() - start_time

        # 7. Guardar en BD
        new_report = ActorReport(
            actorName=q,
            reportType=ReportType.DAILY,
            reportData=daily_summary_data,
            summary=(analisis_ia.get("resumen_ejecutivo", "") or "")[:500],
            generationTime=generation_time,
            itemCount=total_menciones
        )

        db.add(new_report)
        await db.commit()
        await db.refresh(new_report)

        print(f"✅ Resumen diario guardado (ID: {new_report.id}) - {total_menciones} menciones")

        return {
            **daily_summary_data,
            "_metadata": {
                "from_cache": False,
                "generated_at": new_report.createdAt.isoformat(),
                "report_id": new_report.id,
                "generation_time": round(generation_time, 2),
                "campaign_id": campaign.id,
                "analyzed_by": "perplexity"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error al generar resumen diario: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error al generar el resumen diario: {e}")


# -----------------------------------------------------------------------------------
# NUEVO: Endpoint para ver histórico de reportes
# -----------------------------------------------------------------------------------

@router.get("/reports/history")
async def get_reports_history(
    actor_name: str = Query(..., description="Nombre del actor"),
    report_type: Optional[str] = Query(None, description="Filtrar por tipo: 'weekly' o 'daily'"),
    limit: int = Query(50, ge=1, le=200, description="Número máximo de reportes"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
    db: AsyncSession = Depends(get_session)
):
    """
    Obtiene el histórico de reportes de un actor.
    
    Útil para:
    - Ver evolución temporal
    - Comparar reportes pasados
    - Análisis de tendencias
    """
    try:
        query = select(ActorReport).where(
            ActorReport.actorName == actor_name
        )
        
        if report_type:
            query = query.where(ActorReport.reportType == ReportType(report_type))
        
        query = query.order_by(desc(ActorReport.createdAt)).limit(limit).offset(offset)
        
        result = await db.execute(query)
        reports = result.scalars().all()
        
        # Formato simplificado para listado
        return {
            "actor_name": actor_name,
            "total": len(reports),
            "reports": [
                {
                    "id": r.id,
                    "type": r.reportType.value,
                    "created_at": r.createdAt.isoformat(),
                    "summary": r.summary,
                    "item_count": r.itemCount,
                    "generation_time": r.generationTime
                }
                for r in reports
            ]
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener histórico: {e}")


# -----------------------------------------------------------------------------------
# NUEVO: Endpoint para obtener un reporte específico por ID
# -----------------------------------------------------------------------------------

@router.get("/reports/{report_id}")
async def get_report_by_id(
    report_id: str,
    db: AsyncSession = Depends(get_session)
):
    """
    Obtiene un reporte específico por su ID.
    Útil para ver reportes históricos completos.
    """
    try:
        result = await db.execute(
            select(ActorReport).where(ActorReport.id == report_id)
        )
        report = result.scalars().first()
        
        if not report:
            raise HTTPException(status_code=404, detail="Reporte no encontrado")
        
        return {
            **report.reportData,
            "_metadata": {
                "report_id": report.id,
                "actor_name": report.actorName,
                "report_type": report.reportType.value,
                "generated_at": report.createdAt.isoformat(),
                "generation_time": report.generationTime,
                "item_count": report.itemCount
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener reporte: {e}")