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

BOOST_MEDIOS_LOCALES = 1.5  # Multiplicador de score para medios locales


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
        async with httpx.AsyncClient(timeout=15) as client:
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
        if len(keyword) > 3 and keyword in title_lower:  # Ignorar palabras muy cortas
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


class PerplexityService:
    def __init__(self):
        self.client = AsyncPerplexity()

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
        
        ✅ CORRECCIONES:
        - max_results SIEMPRE <= 20 (límite de API)
        - Mejor cálculo de scoring
        - Manejo robusto de errores
        """
        print(f"\n{'='*70}")
        print(f"🔍 BÚSQUEDA ITERATIVA CON MEDIOS LOCALES")
        print(f"   Campaña: {campaign_name}")
        print(f"   Query: {query[:100]}...")
        print(f"   Medios locales: {'✅ PRIORIZADOS' if priorizar_medios_locales else '❌ No'}")
        print(f"{'='*70}\n")

        formatted_start = to_mmddyyyy(start_date)
        formatted_end = to_mmddyyyy(end_date)

        analyzed_articles = []
        
        # ✅ CORRECCIÓN: max_results NUNCA excede 20
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
                for result, score in filtered_results[:15]:  # Máximo 15
                    print(f"\n📄 Analizando: {result.title[:70]}...")
                    print(f"   URL: {result.url[:80]}...")
                    print(f"   Score: {score:.2f} {'🏠' if es_medio_local(result.url) else '🌐'}")

                    content = await _get_url_content(result.url)
                    if not content:
                        print(f"   ⚠️ Sin contenido, saltando...")
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

                    try:
                        chat_response = await self.client.chat.completions.create(
                            model="sonar-reasoning",
                            messages=[
                                {"role": "system", "content": "Eres un analista de medios que responde solo con objetos JSON."},
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
                        analysis_json = json.loads(analysis_content)

                        # Solo agregar si tiene contenido relevante
                        if analysis_json and analysis_json.get("summary"):
                            analyzed_articles.append({
                                "title": result.title,
                                "url": result.url,
                                "publishedAt": getattr(result, 'published_date', None),
                                "summary": analysis_json.get("summary", ""),
                                "sentiment_label": analysis_json.get("sentiment_label", "Neutral"),
                                "sentiment_score": analysis_json.get("sentiment_score", 0.0),
                                "topics": analysis_json.get("topics", []),
                                "key_points": analysis_json.get("key_points", []),
                                "relevance_score": score,
                                "es_medio_local": es_medio_local(result.url)
                            })
                            print(f"   ✅ Agregado (Total: {len(analyzed_articles)})")

                    except json.JSONDecodeError as e:
                        print(f"   ⚠️ Error JSON: {e}")
                        continue
                    except Exception as e:
                        print(f"   ⚠️ Error al analizar: {e}")
                        continue

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
            print(f"   🏠 Medios locales: {locales}")
        print(f"{'='*70}\n")

        return analyzed_articles

    async def get_daily_actor_summary(self, actor_name: str) -> Dict[str, Any]:
        """Resumen diario con énfasis en medios locales."""
        print(f"\n📰 Generando resumen diario para: {actor_name}")

        medios_str = ", ".join(MEDIOS_LOCALES_TAMPICO[:4])
        
        analysis_prompt = f"""
Realiza una búsqueda automatizada sobre el actor político "{actor_name}" en medios digitales, prensa y redes sociales, 
priorizando ESPECIALMENTE medios locales de Tampico como: {medios_str}.

Limítate a las 5-10 notas más relevantes de las últimas 24 horas.

Formato JSON:
{{
  "resumen_diario_express": "Texto en máximo 3 líneas",
  "registro_de_evidencia": [
    {{
      "descripcion": "Descripción de la nota",
      "fecha": "YYYY-MM-DD",
      "link": "https://...",
      "medio": "Nombre del medio",
      "es_local": true/false
    }}
  ]
}}

Responde SOLO con el JSON, sin texto adicional.
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Eres un analista de medios especializado en prensa local de Tampico. Respondes SOLO con JSON válido."},
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
                                            "link": {"type": "string", "format": "uri"},
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
            
            # ✅ Validación robusta de JSON
            if not analysis_content or analysis_content.strip() == "":
                print(f"⚠️ Respuesta vacía de la API")
                return {"error": "Respuesta vacía de la API"}
            
            analysis_json = json.loads(analysis_content)
            
            # Ordenar evidencias: medios locales primero
            if "registro_de_evidencia" in analysis_json:
                analysis_json["registro_de_evidencia"].sort(
                    key=lambda x: (not x.get("es_local", False), x.get("fecha", ""))
                )
            
            print(f"✅ Resumen diario generado con {len(analysis_json.get('registro_de_evidencia', []))} evidencias")
            return analysis_json

        except json.JSONDecodeError as e:
            print(f"❌ Error decodificando JSON: {e}")
            return {"error": f"Error decodificando JSON: {str(e)}"}
        except Exception as e:
            print(f"❌ Error en resumen diario: {e}")
            return {"error": str(e)}

    async def get_weekly_actor_report(self, actor_name: str) -> Dict[str, Any]:
        """Reporte semanal con énfasis en medios locales."""
        print(f"\n📊 Generando reporte semanal para: {actor_name}")

        medios_str = ", ".join(MEDIOS_LOCALES_TAMPICO)
        
        analysis_prompt = f"""
Realiza un análisis semanal integral sobre "{actor_name}", priorizando ESPECIALMENTE 
medios locales de Tampico: {medios_str}.

Formato JSON:
{{
  "resumen_ejecutivo": "Texto con hechos, tendencias y métricas",
  "analisis_estrategico": "Texto con narrativas, FODA y análisis político",
  "log_de_evidencia": [
    {{
      "descripcion": "Descripción",
      "fecha": "YYYY-MM-DD",
      "tipo_medio": "Tipo de medio",
      "link": "https://...",
      "es_medio_local": true/false
    }}
  ]
}}

Responde SOLO con el JSON, sin texto adicional.
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Eres un analista político especializado en medios locales de Tampico. Respondes SOLO con JSON válido."},
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
            
            # ✅ Validación robusta de JSON
            if not analysis_content or analysis_content.strip() == "":
                print(f"⚠️ Respuesta vacía de la API")
                return {"error": "Respuesta vacía de la API"}
            
            analysis_json = json.loads(analysis_content)
            
            # Ordenar evidencias: medios locales primero
            if "log_de_evidencia" in analysis_json:
                analysis_json["log_de_evidencia"].sort(
                    key=lambda x: (not x.get("es_medio_local", False), x.get("fecha", ""))
                )
            
            print(f"✅ Reporte semanal generado con {len(analysis_json.get('log_de_evidencia', []))} evidencias")
            return analysis_json

        except json.JSONDecodeError as e:
            print(f"❌ Error decodificando JSON: {e}")
            return {"error": f"Error decodificando JSON: {str(e)}"}
        except Exception as e:
            print(f"❌ Error en reporte semanal: {e}")
            return {"error": str(e)}


# Instancia global del servicio
perplexity_service = PerplexityService()