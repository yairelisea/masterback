# app/services/perplexity_service.py
from __future__ import annotations
import os
import httpx
import json
import re
import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
from perplexity import AsyncPerplexity, PerplexityError

logger = logging.getLogger(__name__)

async def _get_url_content(url: str, max_retries: int = 2) -> str:
    """
    ✅ Resiliente: timeout, retry, validación de contenido
    """
    for attempt in range(max_retries):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            timeout = httpx.Timeout(10.0, connect=5.0)
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    url, 
                    headers=headers, 
                    follow_redirects=True
                )
                resp.raise_for_status()
                
                # ✅ Validar tamaño
                if len(resp.content) > 2_000_000:  # 2MB max
                    logger.warning(f"⚠️ Content too large: {url} ({len(resp.content)} bytes)")
                    return ""
                
                # ✅ Validar que sea texto
                content_type = resp.headers.get("content-type", "").lower()
                if "text" not in content_type and "html" not in content_type:
                    logger.warning(f"⚠️ Non-text content: {url} ({content_type})")
                    return ""
                
                text = resp.text[:10_000]  # ✅ Truncar
                
                # ✅ Validar contenido mínimo
                if len(text.strip()) < 100:
                    logger.warning(f"⚠️ Insufficient content: {url}")
                    return ""
                
                return text
                
        except httpx.TimeoutException:
            logger.warning(f"⏱️ Timeout fetching {url} (attempt {attempt + 1})")
            if attempt == max_retries - 1:
                return ""
            await asyncio.sleep(2)
            
        except httpx.HTTPStatusError as e:
            logger.warning(f"⚠️ HTTP {e.response.status_code} for {url}")
            return ""  # ✅ No retry en 404, 403, etc.
            
        except Exception as e:
            logger.warning(f"⚠️ Error fetching {url}: {e}")
            return ""
    
    return ""

def to_mmddyyyy(date_str: Optional[str]) -> Optional[str]:
    if not date_str:
        return None
    # Si ya está en MM/DD/YYYY, la deja igual
    if re.match(r"\d{2}/\d{2}/\d{4}$", date_str):
        return date_str
    # Si viene como YYYY-MM-DD, la convierte
    if re.match(r"\d{4}-\d{2}-\d{2}$", date_str):
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").strftime("%m/%d/%Y")
        except Exception as e:
            logger.error(f"Error formateando la fecha '{date_str}': {e}")
            return None
    logger.warning(f"Formato de fecha no reconocido: '{date_str}'")
    return None


class PerplexityService:
    def __init__(self):
        self.client = AsyncPerplexity()

    async def search_and_analyze(
        self, 
        query: str, 
        campaign_name: str, 
        city_keywords: Optional[List[str]] = None,
        start_date: Optional[str] = None, 
        end_date: Optional[str] = None,
        max_retries: int = 3,
        min_relevance_score: float = 40.0
    ) -> List[Dict[str, Any]]:
        """
        ✅ Resiliente: maneja timeouts, rate limits, errores parciales
        ✅ Con filtrado en capas (pre-filtro + análisis)
        """
        logger.info(f"🔍 Perplexity search: query='{query[:50]}...', campaign='{campaign_name}'")

        # Formatear fechas
        formatted_start = to_mmddyyyy(start_date)
        formatted_end = to_mmddyyyy(end_date)

        # ✅ RETRY LOOP para la búsqueda
        search_results = None
        last_error = None
        
        for attempt in range(max_retries):
            try:
                search_params = {
                    "query": query,
                    "max_results": 15,
                }
                if formatted_start:
                    search_params["search_after_date_filter"] = formatted_start
                if formatted_end:
                    search_params["search_before_date_filter"] = formatted_end

                search_results = await asyncio.wait_for(
                    self.client.search.create(**search_params),
                    timeout=30.0  # ✅ Timeout de 30 seg
                )
                logger.info(f"✅ Search successful: {len(search_results.results)} results")
                break  # ✅ Éxito - salir del retry loop
                
            except asyncio.TimeoutError:
                last_error = f"Timeout on attempt {attempt + 1}"
                logger.warning(f"⏱️ {last_error}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    
            except PerplexityError as e:
                last_error = str(e)
                logger.error(f"❌ Perplexity API error (attempt {attempt + 1}): {e}")
                if "rate limit" in str(e).lower():
                    await asyncio.sleep(10)
                elif attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.error(f"Giving up after {max_retries} attempts")
                    return []
                    
            except Exception as e:
                last_error = str(e)
                logger.error(f"❌ Unexpected error (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    return []

        # ✅ Si falló después de todos los retries
        if not search_results or not search_results.results:
            logger.error(f"❌ Search failed after {max_retries} attempts: {last_error}")
            return []

        logger.info(f"📊 Got {len(search_results.results)} raw results from Perplexity")

        # ✅ CAPA 1: Filtrar por fecha (últimas 2 semanas)
        recent_results = []
        two_weeks_ago = datetime.now(timezone.utc) - timedelta(days=14)

        for result in search_results.results:
            if hasattr(result, "publishedAt") and result.publishedAt:
                try:
                    published_date = result.publishedAt
                    if not isinstance(published_date, datetime):
                        published_date = datetime.fromisoformat(str(published_date).replace("Z", "+00:00"))
                    
                    if published_date.tzinfo is None:
                        published_date = published_date.replace(tzinfo=timezone.utc)

                    if published_date >= two_weeks_ago:
                        recent_results.append(result)
                except (ValueError, TypeError):
                    # Si la fecha es inválida, se omite
                    continue
            else:
                # Si no hay fecha, lo dejamos pasar por ahora
                recent_results.append(result)
        
        logger.info(f"📅 After date filtering: {len(recent_results)}/{len(search_results.results)} recent")

        # ✅ CAPA 2: Pre-filtro rápido (implementado en siguiente sección)
        from .relevance_filter import quick_relevance_check
        
        filtered_results = []
        for idx, result in enumerate(recent_results):
            is_relevant, score = await quick_relevance_check(
                result_title=result.title,
                result_url=result.url,
                actor_name=campaign_name,
                city_keywords=city_keywords,
            )
            
            if is_relevant and score >= min_relevance_score:
                filtered_results.append((result, score))
                logger.debug(f"✅ Result {idx} PASSED pre-filter (score: {score:.1f}): {result.title[:60]}")
            else:
                logger.debug(f"⛔ Result {idx} REJECTED (score: {score:.1f}): {result.title[:60]}")
        
        filtered_results.sort(key=lambda x: x[1], reverse=True)
        logger.info(f"🎯 After pre-filter: {len(filtered_results)}/{len(search_results.results)} relevant")
        
        if not filtered_results:
            logger.warning("⚠️ No relevant results after pre-filtering")
            return []

        # ✅ CAPA 3: Análisis profundo solo para resultados filtrados
        analyzed_articles = []
        
        for idx, (result, pre_score) in enumerate(filtered_results[:10]):
            try:
                # ✅ Timeout individual para cada artículo
                content = await asyncio.wait_for(
                    _get_url_content(result.url),
                    timeout=15.0
                )
                
                if not content or len(content.strip()) < 100:
                    logger.warning(f"⚠️ Article {idx} has insufficient content: {result.url}")
                    continue

                # ✅ Análisis con IA (con timeout)
                analysis_prompt = f"""
Analiza el siguiente texto sobre política mexicana.
Si '{campaign_name}' NO tiene relevancia, responde solo {{}}
Si SÍ es relevante, responde con este objeto JSON:
- summary: resumen conciso (2-3 frases)
- sentiment_label: 'Positivo', 'Negativo' o 'Neutral'
- sentiment_score: de -1.0 a 1.0
- topics: 3-5 temas principales
- key_points: 2-3 citas o puntos clave

Texto:
{content[:4000]}

Responde solo con el objeto JSON.
"""

                chat_response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model="sonar-reasoning",
                        messages=[
                            {"role": "system", "content": "Eres un analista de medios que responde solo con objetos JSON definidos por el usuario."},
                            {"role": "user", "content": analysis_prompt},
                        ],
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "summary": {"type": "string"},
                                        "sentiment_label": {"type": "string", "enum": ["Positivo", "Negativo", "Neutral"]},
                                        "sentiment_score": {"type": "number"},
                                        "topics": {"type": "array", "items": {"type": "string"}},
                                        "key_points": {"type": "array", "items": {"type": "string"}}
                                    },
                                    "required": ["summary", "sentiment_label", "sentiment_score", "topics", "key_points"]
                                }
                            }
                        },
                    ),
                    timeout=20.0
                )

                analysis_content = chat_response.choices[0].message.content

                # ✅ Parse JSON con validación
                json_match = re.search(r"({.*})", analysis_content, re.DOTALL)
                if not json_match:
                    logger.warning(f"⚠️ No JSON found in IA response for {result.url}")
                    continue

                only_json = json_match.group(1)
                analysis_json = json.loads(only_json)
                
                # ✅ Validar campos requeridos
                if not analysis_json.get("summary"):
                    logger.warning(f"⚠️ Empty summary for {result.url}")
                    continue
                
                # ✅ VALIDACIÓN FINAL: verificar que mencione al actor
                summary_lower = analysis_json.get("summary", "").lower()
                actor_lower = campaign_name.lower()
                
                has_actor = actor_lower in summary_lower
                has_city = any((c or "").lower() in summary_lower for c in (city_keywords or []))
                
                if not has_actor and not has_city:
                    logger.warning(f"⚠️ Analysis doesn't mention actor/city: {result.url}")
                    continue
                
                analyzed_articles.append({
                    "title": result.title,
                    "url": result.url,
                    "publishedAt": getattr(result, "publishedAt", None),
                    "_relevance_score": pre_score,
                    **analysis_json
                })
                
                logger.debug(f"✅ Analyzed article {idx + 1}/{len(filtered_results)}")

            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Timeout analyzing article {idx}: {result.url}")
                continue
                
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ Invalid JSON for article {idx}: {e}")
                continue
                
            except Exception as e:
                logger.error(f"❌ Error processing article {idx} ({result.url}): {e}")
                continue

        logger.info(f"✅ Analysis complete: {len(analyzed_articles)}/{len(search_results.results)} successful")
        return analyzed_articles

    async def analyze_urls(
        self,
        urls: List[str],
        campaign_name: str,
    ) -> List[Dict[str, Any]]:
        logger.info(f"🔎 Analyzing {len(urls)} URLs for campaign '{campaign_name}'")

        analyzed_articles = []
        for idx, url in enumerate(urls):
            try:
                content = await asyncio.wait_for(
                    _get_url_content(url),
                    timeout=30.0
                )

                if not content or len(content.strip()) < 100:
                    logger.warning(f"⚠️ Article {idx} has insufficient content: {url}")
                    continue

                analysis_prompt = f"""
Analiza el siguiente texto sobre política mexicana.
Si '{campaign_name}' NO tiene relevancia, responde solo {{}}
Si SÍ es relevante, responde con este objeto JSON:
- summary: resumen conciso (2-3 frases)
- sentiment_label: 'Positivo', 'Negativo' o 'Neutral'
- sentiment_score: de -1.0 a 1.0
- topics: 3-5 temas principales
- key_points: 2-3 citas o puntos clave

Texto:
{content[:4000]}

Responde solo con el objeto JSON.
"""

                chat_response = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model="sonar-reasoning",
                        messages=[
                            {"role": "system", "content": "Eres un analista de medios que responde solo con objetos JSON definidos por el usuario."},
                            {"role": "user", "content": analysis_prompt},
                        ],
                        response_format={
                            "type": "json_schema",
                            "json_schema": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "summary": {"type": "string"},
                                        "sentiment_label": {"type": "string", "enum": ["Positivo", "Negativo", "Neutral"]},
                                        "sentiment_score": {"type": "number"},
                                        "topics": {"type": "array", "items": {"type": "string"}},
                                        "key_points": {"type": "array", "items": {"type": "string"}}
                                    },
                                    "required": ["summary", "sentiment_label", "sentiment_score", "topics", "key_points"]
                                }
                            }
                        },
                    ),
                    timeout=20.0
                )

                analysis_content = chat_response.choices[0].message.content

                json_match = re.search(r"({.*})", analysis_content, re.DOTALL)
                if not json_match:
                    logger.warning(f"⚠️ No JSON found in IA response for {url}")
                    continue

                only_json = json_match.group(1)
                try:
                    analysis_json = json.loads(only_json)
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠️ Invalid JSON for article {idx}: {e}")
                    logger.warning(f"Raw response from Perplexity: {analysis_content}")
                    continue

                if not analysis_json.get("summary"):
                    logger.warning(f"⚠️ Empty summary for {url}")
                    continue

                analyzed_articles.append({
                    "title": url,
                    "url": url,
                    "publishedAt": None,
                    **analysis_json
                })

                logger.debug(f"✅ Analyzed article {idx + 1}/{len(urls)}")

            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Timeout analyzing article {idx}: {url}")
                continue
            except Exception as e:
                logger.error(f"❌ Error processing article {idx} ({url}): {e}")
                continue

        logger.info(f"✅ Analysis complete: {len(analyzed_articles)}/{len(urls)} successful")
        return analyzed_articles

    # ✅ Funciones de reportes (las actualizaremos en Fase 3)
    async def get_daily_actor_summary(self, actor_name: str) -> Dict[str, Any]:
        """Placeholder - se actualizará en Fase 3"""
        return {"error": "Not implemented yet"}

    async def get_weekly_actor_report(self, actor_name: str) -> Dict[str, Any]:
        """Placeholder - se actualizará en Fase 3"""
        return {"error": "Not implemented yet"}


# Instancia global
perplexity_service = PerplexityService()