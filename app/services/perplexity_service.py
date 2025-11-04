from __future__ import annotations
import os
import httpx
import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from perplexity import AsyncPerplexity, PerplexityError

# ============================================================================
# CONFIGURACIÓN DE MEDIOS LOCALES PRIORITARIOS
# ============================================================================
MEDIOS_LOCALES_TAMPICO = [
    "soldetampico.com.mx",
    "elsoldeltampico.com",
    "elsoldetampico.com.mx",
    "milenio.com",
    "telediario.mx",
    "expreso.press",
    "expresopress.com",
    "hoytamaulipas.net",
    "laverdaddetamaulipas.com",
    "elpulsodetampico.com"
]

BOOST_MEDIOS_LOCALES = 1.5


def to_mmddyyyy(date_str: Optional[str]) -> Optional[str]:
    """Convierte fechas al formato MM/DD/YYYY requerido por Perplexity."""
    if not date_str:
        return None
    if re.match(r"\d{2}/\d{2}/\d{4}$", date_str):
        return date_str
    if re.match(r"\d{4}-\d{2}-\d{2}$", date_str):
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").strftime("%m/%d/%Y")
        except Exception as e:
            print(f"Error formateando la fecha '{date_str}': {e}")
            return None
    print(f"Formato de fecha no reconocido: '{date_str}'")
    return None


async def _get_url_content(url: str) -> str:
    """Obtiene el contenido de texto de una URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        print(f"⚠️ Error al obtener contenido de {url}: {e}")
        return ""


def es_medio_local(url: str) -> bool:
    """Determina si una URL pertenece a un medio local prioritario."""
    url_lower = url.lower()
    return any(medio in url_lower for medio in MEDIOS_LOCALES_TAMPICO)


def calcular_score_relevancia(result: Any, campaign_name: str, boost_local: bool = True) -> float:
    """
    Calcula un score de relevancia basado en:
    - Presencia del campaign_name en título/snippet
    - Si es medio local (boost)
    """
    score = 0.0
    campaign_lower = campaign_name.lower()
    
    # Extraer palabras clave del campaign_name
    keywords = campaign_lower.split()
    
    # Boost por keywords en título
    title_lower = result.title.lower()
    for keyword in keywords:
        if len(keyword) > 3 and keyword in title_lower:
            score += 1.0
    
    # Boost por keywords en snippet
    if hasattr(result, 'snippet') and result.snippet:
        snippet_lower = result.snippet.lower()
        for keyword in keywords:
            if len(keyword) > 3 and keyword in snippet_lower:
                score += 0.5
    
    # BOOST ADICIONAL para medios locales
    if boost_local and es_medio_local(result.url):
        score *= BOOST_MEDIOS_LOCALES
        print(f"🏠 MEDIO LOCAL: {result.url[:80]}... | Score: {score:.2f}")
    
    return score


def crear_analisis_fallback(title: str, url: str, relevance_score: float, es_local: bool) -> Dict[str, Any]:
    """
    Crea un análisis básico cuando la API no responde.
    Usado como FALLBACK cuando el análisis JSON falla.
    """
    return {
        "title": title,
        "url": url,
        "publishedAt": None,
        "summary": f"Artículo sobre el tema analizado. Título: {title[:100]}",
        "sentiment_label": "Neutral",
        "sentiment_score": 0.0,
        "topics": ["política", "noticias"],
        "key_points": ["Ver artículo completo en la fuente"],
        "relevance_score": relevance_score,
        "es_medio_local": es_local,
        "_fallback": True  # Marca que fue creado con fallback
    }


class PerplexityService:
    def __init__(self):
        self.client = AsyncPerplexity()

    async def _analizar_articulo_con_fallback(
        self, 
        result: Any, 
        campaign_name: str, 
        content: str, 
        relevance_score: float
    ) -> Optional[Dict[str, Any]]:
        """
        Intenta analizar un artículo con múltiples estrategias:
        1. Análisis completo con JSON schema
        2. Análisis simple sin schema (si falla el primero)
        3. Fallback con datos básicos (si todo falla)
        """
        es_local = es_medio_local(result.url)
        
        # ========== INTENTO 1: Análisis con JSON Schema ==========
        try:
            analysis_prompt = f"""
Analiza este artículo sobre '{campaign_name}'.

Responde SOLO con JSON válido:
{{
  "summary": "Resumen en 2-3 frases",
  "sentiment_label": "Positivo|Negativo|Neutral",
  "sentiment_score": 0.5,
  "topics": ["tema1", "tema2"],
  "key_points": ["punto1", "punto2"]
}}

Artículo:
{content[:3000]}
"""

            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Eres un analista de medios. Respondes SOLO con JSON válido."},
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "news_analysis",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "summary": {"type": "string"},
                                "sentiment_label": {"type": "string"},
                                "sentiment_score": {"type": "number"},
                                "topics": {"type": "array", "items": {"type": "string"}},
                                "key_points": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["summary", "sentiment_label", "sentiment_score", "topics", "key_points"],
                            "additionalProperties": False,
                        },
                    },
                },
            )

            analysis_content = chat_response.choices[0].message.content
            
            # Validar que no esté vacío
            if not analysis_content or analysis_content.strip() == "":
                print(f"   ⚠️ Respuesta vacía, intentando método alternativo...")
                raise ValueError("Respuesta vacía")
            
            analysis_json = json.loads(analysis_content)
            
            # Validar que tenga contenido útil
            if not analysis_json.get("summary") or len(analysis_json.get("summary", "")) < 10:
                print(f"   ⚠️ Análisis sin contenido útil, intentando método alternativo...")
                raise ValueError("Análisis vacío")
            
            # ✅ ÉXITO: Análisis completo
            return {
                "title": result.title,
                "url": result.url,
                "publishedAt": getattr(result, 'published_date', None),
                "summary": analysis_json.get("summary", ""),
                "sentiment_label": analysis_json.get("sentiment_label", "Neutral"),
                "sentiment_score": analysis_json.get("sentiment_score", 0.0),
                "topics": analysis_json.get("topics", []),
                "key_points": analysis_json.get("key_points", []),
                "relevance_score": relevance_score,
                "es_medio_local": es_local,
                "_fallback": False
            }
            
        except (json.JSONDecodeError, ValueError) as e:
            print(f"   ⚠️ Intento 1 falló: {e}")
            pass  # Continuar al intento 2
        except Exception as e:
            print(f"   ⚠️ Error inesperado en intento 1: {e}")
            pass

        # ========== INTENTO 2: Análisis Simple SIN Schema ==========
        try:
            print(f"   🔄 Intentando análisis simple...")
            
            simple_prompt = f"""
Analiza brevemente este artículo sobre '{campaign_name}'.

Responde en formato JSON simple:
{{"summary": "resumen breve", "sentiment": "positivo/negativo/neutral"}}

Texto: {content[:2000]}
"""

            simple_response = await self.client.chat.completions.create(
                model="sonar",  # Modelo más simple
                messages=[
                    {"role": "user", "content": simple_prompt},
                ],
            )
            
            simple_content = simple_response.choices[0].message.content
            
            if simple_content and simple_content.strip():
                # Intentar parsear el JSON
                simple_json = json.loads(simple_content)
                
                # ✅ ÉXITO: Análisis simple
                print(f"   ✅ Análisis simple exitoso")
                return {
                    "title": result.title,
                    "url": result.url,
                    "publishedAt": getattr(result, 'published_date', None),
                    "summary": simple_json.get("summary", f"Artículo sobre {campaign_name}"),
                    "sentiment_label": simple_json.get("sentiment", "Neutral").capitalize(),
                    "sentiment_score": 0.0,
                    "topics": [campaign_name, "política"],
                    "key_points": ["Ver fuente original"],
                    "relevance_score": relevance_score,
                    "es_medio_local": es_local,
                    "_fallback": "simple"
                }
        except Exception as e:
            print(f"   ⚠️ Intento 2 falló: {e}")
            pass

        # ========== INTENTO 3: FALLBACK - Datos Básicos ==========
        print(f"   ⚙️ Usando datos básicos (fallback)")
        return crear_analisis_fallback(result.title, result.url, relevance_score, es_local)

    async def search_and_analyze(
        self, 
        query: str, 
        campaign_name: str, 
        start_date: Optional[str] = None, 
        end_date: Optional[str] = None,
        priorizar_medios_locales: bool = True
    ) -> List[Dict[str, Any]]:
        """
        BÚSQUEDA ITERATIVA con priorización de medios locales.
        ULTRA ROBUSTA con múltiples estrategias de análisis.
        """
        print(f"\n{'='*70}")
        print(f"🔍 BÚSQUEDA ITERATIVA ULTRA ROBUSTA")
        print(f"   Campaña: {campaign_name}")
        print(f"   Query: {query[:100]}...")
        print(f"   Medios locales: {'✅ PRIORIZADOS' if priorizar_medios_locales else '❌ No'}")
        print(f"{'='*70}\n")

        formatted_start = to_mmddyyyy(start_date)
        formatted_end = to_mmddyyyy(end_date)

        analyzed_articles = []
        
        intentos = [
            {"max_results": 20, "threshold": 1.5, "nombre": "ESTRICTO"},
            {"max_results": 20, "threshold": 1.0, "nombre": "MEDIO"},
            {"max_results": 20, "threshold": 0.5, "nombre": "RELAJADO"}
        ]

        for i, config in enumerate(intentos, 1):
            print(f"\n{'─'*70}")
            print(f"🔄 INTENTO {i}/3 - Modo {config['nombre']}")
            print(f"   Max resultados: {config['max_results']}, Umbral: {config['threshold']}")
            print(f"{'─'*70}")

            try:
                # === BÚSQUEDA GENERAL ===
                search_params = {
                    "query": query,
                    "max_results": config["max_results"],
                }
                if formatted_start:
                    search_params["search_after_date_filter"] = formatted_start
                if formatted_end:
                    search_params["search_before_date_filter"] = formatted_end

                search_results = await self.client.search.create(**search_params)
                
                # Calcular scores y filtrar
                scored_results = []
                for result in search_results.results:
                    score = calcular_score_relevancia(result, campaign_name, boost_local=priorizar_medios_locales)
                    scored_results.append((result, score))
                
                # Ordenar por score descendente
                scored_results.sort(key=lambda x: x[1], reverse=True)
                
                # Filtrar por umbral
                filtered_results = [
                    (result, score) for result, score in scored_results 
                    if score >= config["threshold"]
                ]
                
                print(f"\n📊 Resultados:")
                print(f"   Total encontrados: {len(search_results.results)}")
                print(f"   ✅ Relevantes (>= {config['threshold']}): {len(filtered_results)}")
                
                if priorizar_medios_locales:
                    medios_locales_count = sum(1 for result, _ in filtered_results if es_medio_local(result.url))
                    print(f"   🏠 Medios locales: {medios_locales_count}")

                # Analizar artículos filtrados
                for result, score in filtered_results[:15]:
                    print(f"\n📄 Analizando: {result.title[:70]}...")
                    print(f"   URL: {result.url[:80]}...")
                    print(f"   Score: {score:.2f} {'🏠' if es_medio_local(result.url) else '🌐'}")

                    content = await _get_url_content(result.url)
                    if not content:
                        print(f"   ⚠️ Sin contenido, usando fallback básico")
                        # Aún así agregamos el artículo con datos básicos
                        article = crear_analisis_fallback(
                            result.title, 
                            result.url, 
                            score, 
                            es_medio_local(result.url)
                        )
                        analyzed_articles.append(article)
                        print(f"   ✅ Agregado con datos básicos (Total: {len(analyzed_articles)})")
                        continue

                    # ✅ Intentar análisis con fallback automático
                    article = await self._analizar_articulo_con_fallback(
                        result, campaign_name, content, score
                    )
                    
                    if article:
                        analyzed_articles.append(article)
                        fallback_type = article.get("_fallback", False)
                        if fallback_type == True:
                            print(f"   ✅ Agregado con fallback básico (Total: {len(analyzed_articles)})")
                        elif fallback_type == "simple":
                            print(f"   ✅ Agregado con análisis simple (Total: {len(analyzed_articles)})")
                        else:
                            print(f"   ✅ Agregado con análisis completo (Total: {len(analyzed_articles)})")

                # Verificar si ya tenemos suficientes resultados
                if len(analyzed_articles) >= 3:
                    print(f"\n✅ ÉXITO: {len(analyzed_articles)} artículos encontrados")
                    break

            except PerplexityError as e:
                print(f"❌ Error en API de Perplexity (intento {i}): {e}")
                if i == len(intentos):
                    print(f"⚠️ Agotados todos los intentos, retornando {len(analyzed_articles)} artículos")
                    break
                continue

        # Ordenar resultados finales: medios locales primero
        if priorizar_medios_locales and analyzed_articles:
            analyzed_articles.sort(key=lambda x: (not x["es_medio_local"], -x["relevance_score"]))

        print(f"\n{'='*70}")
        print(f"📊 RESUMEN FINAL:")
        print(f"   Total artículos: {len(analyzed_articles)}")
        if priorizar_medios_locales and analyzed_articles:
            locales = sum(1 for art in analyzed_articles if art["es_medio_local"])
            fallbacks = sum(1 for art in analyzed_articles if art.get("_fallback"))
            print(f"   🏠 Medios locales: {locales}")
            print(f"   ⚙️ Con fallback: {fallbacks}")
        print(f"{'='*70}\n")

        return analyzed_articles

    async def get_daily_actor_summary(self, actor_name: str) -> Dict[str, Any]:
        """Resumen diario con énfasis en medios locales."""
        print(f"\n📰 Generando resumen diario para: {actor_name}")

        medios_str = ", ".join(MEDIOS_LOCALES_TAMPICO[:4])
        
        analysis_prompt = f"""
Realiza una búsqueda sobre "{actor_name}" en medios digitales, priorizando medios locales de Tampico: {medios_str}.

Responde SOLO con JSON válido:
{{
  "resumen_diario_express": "Texto en máximo 3 líneas",
  "registro_de_evidencia": [
    {{
      "descripcion": "Descripción",
      "fecha": "YYYY-MM-DD",
      "link": "https://...",
      "medio": "Nombre del medio",
      "es_local": true
    }}
  ]
}}
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Analista de medios. Respondes SOLO con JSON válido."},
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "daily_summary",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "resumen_diario_express": {"type": "string"},
                                "registro_de_evidencia": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "descripcion": {"type": "string"},
                                            "fecha": {"type": "string"},
                                            "link": {"type": "string"},
                                            "medio": {"type": "string"},
                                            "es_local": {"type": "boolean"}
                                        },
                                        "required": ["descripcion", "fecha", "link", "medio"]
                                    }
                                }
                            },
                            "required": ["resumen_diario_express", "registro_de_evidencia"],
                            "additionalProperties": False
                        }
                    }
                },
            )

            analysis_content = chat_response.choices[0].message.content
            
            if not analysis_content or analysis_content.strip() == "":
                print(f"⚠️ Respuesta vacía de la API para resumen diario")
                return {
                    "resumen_diario_express": f"Resumen no disponible para {actor_name}",
                    "registro_de_evidencia": []
                }
            
            try:
                analysis_json = json.loads(analysis_content)
            except json.JSONDecodeError as je:
                print(f"⚠️ Error decodificando JSON en resumen diario: {je}")
                return {
                    "resumen_diario_express": f"Resumen básico para {actor_name}",
                    "registro_de_evidencia": []
                }
            
            # Validar que sea un diccionario
            if not isinstance(analysis_json, dict):
                print(f"⚠️ Respuesta no es un diccionario válido")
                return {
                    "resumen_diario_express": f"Resumen básico para {actor_name}",
                    "registro_de_evidencia": []
                }
            
            # Asegurar que tenga las claves requeridas
            if "resumen_diario_express" not in analysis_json:
                analysis_json["resumen_diario_express"] = f"Resumen para {actor_name}"
            if "registro_de_evidencia" not in analysis_json:
                analysis_json["registro_de_evidencia"] = []
            
            # Ordenar evidencias
            if isinstance(analysis_json.get("registro_de_evidencia"), list):
                analysis_json["registro_de_evidencia"].sort(
                    key=lambda x: (not x.get("es_local", False), x.get("fecha", ""))
                )
            
            print(f"✅ Resumen diario generado con {len(analysis_json.get('registro_de_evidencia', []))} evidencias")
            return analysis_json

        except json.JSONDecodeError as je:
            print(f"❌ Error decodificando JSON en resumen diario: {je}")
            return {
                "resumen_diario_express": f"Resumen básico para {actor_name}",
                "registro_de_evidencia": []
            }
        except Exception as e:
            print(f"❌ Error inesperado en resumen diario: {e}")
            return {
                "resumen_diario_express": f"Resumen básico para {actor_name}",
                "registro_de_evidencia": []
            }

    async def get_weekly_actor_report(self, actor_name: str) -> Dict[str, Any]:
        """Reporte semanal con énfasis en medios locales."""
        print(f"\n📊 Generando reporte semanal para: {actor_name}")

        medios_str = ", ".join(MEDIOS_LOCALES_TAMPICO)
        
        analysis_prompt = f"""
Análisis semanal de "{actor_name}", priorizando medios locales: {medios_str}.

Responde SOLO con JSON válido:
{{
  "resumen_ejecutivo": "Texto con hechos y métricas",
  "analisis_estrategico": "Texto con FODA y análisis",
  "log_de_evidencia": [
    {{
      "descripcion": "Descripción",
      "fecha": "YYYY-MM-DD",
      "tipo_medio": "Tipo",
      "link": "https://...",
      "es_medio_local": true
    }}
  ]
}}
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Analista político. Respondes SOLO con JSON válido."},
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "weekly_report",
                        "strict": True,
                        "schema": {
                            "type": "object",
                            "properties": {
                                "resumen_ejecutivo": {"type": "string"},
                                "analisis_estrategico": {"type": "string"},
                                "log_de_evidencia": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "descripcion": {"type": "string"},
                                            "fecha": {"type": "string"},
                                            "tipo_medio": {"type": "string"},
                                            "link": {"type": "string"},
                                            "es_medio_local": {"type": "boolean"}
                                        },
                                        "required": ["descripcion", "fecha", "tipo_medio", "link"]
                                    }
                                }
                            },
                            "required": ["resumen_ejecutivo", "analisis_estrategico", "log_de_evidencia"],
                            "additionalProperties": False
                        }
                    }
                },
            )

            analysis_content = chat_response.choices[0].message.content
            
            if not analysis_content or analysis_content.strip() == "":
                print(f"⚠️ Respuesta vacía de la API para reporte semanal")
                return {
                    "resumen_ejecutivo": f"Reporte no disponible para {actor_name}",
                    "analisis_estrategico": "Sin información disponible",
                    "log_de_evidencia": []
                }
            
            try:
                analysis_json = json.loads(analysis_content)
            except json.JSONDecodeError as je:
                print(f"⚠️ Error decodificando JSON en reporte semanal: {je}")
                return {
                    "resumen_ejecutivo": f"Reporte generado para {actor_name}",
                    "analisis_estrategico": "Información limitada disponible",
                    "log_de_evidencia": []
                }
            
            # Validar que sea un diccionario y tenga las claves requeridas
            if not isinstance(analysis_json, dict):
                print(f"⚠️ Respuesta no es un diccionario válido")
                return {
                    "resumen_ejecutivo": f"Reporte generado para {actor_name}",
                    "analisis_estrategico": "Información limitada disponible",
                    "log_de_evidencia": []
                }
            
            # Asegurar que tenga todas las claves requeridas
            if "resumen_ejecutivo" not in analysis_json:
                analysis_json["resumen_ejecutivo"] = f"Resumen para {actor_name}"
            if "analisis_estrategico" not in analysis_json:
                analysis_json["analisis_estrategico"] = "Análisis en proceso"
            if "log_de_evidencia" not in analysis_json:
                analysis_json["log_de_evidencia"] = []
            
            # Ordenar evidencias
            if isinstance(analysis_json.get("log_de_evidencia"), list):
                analysis_json["log_de_evidencia"].sort(
                    key=lambda x: (not x.get("es_medio_local", False), x.get("fecha", ""))
                )
            
            print(f"✅ Reporte semanal generado con {len(analysis_json.get('log_de_evidencia', []))} evidencias")
            return analysis_json

        except json.JSONDecodeError as je:
            print(f"❌ Error decodificando JSON en reporte semanal: {je}")
            return {
                "resumen_ejecutivo": f"Reporte básico para {actor_name}",
                "analisis_estrategico": "Información limitada",
                "log_de_evidencia": []
            }
        except Exception as e:
            print(f"❌ Error inesperado en reporte semanal: {e}")
            return {
                "resumen_ejecutivo": f"Reporte básico para {actor_name}",
                "analisis_estrategico": "Información limitada",
                "log_de_evidencia": []
            }


# Instancia global del servicio
perplexity_service = PerplexityService()