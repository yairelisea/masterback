# app/services/perplexity_service.py
from __future__ import annotations
import os
import httpx
import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from perplexity import AsyncPerplexity, PerplexityError

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
        print(f"Error al obtener contenido de {url}: {e}")
        return ""

def to_mmddyyyy(date_str: Optional[str]) -> Optional[str]:
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

class PerplexityService:
    def __init__(self):
        # Verifica que la API key esté configurada
        api_key = os.getenv("PERPLEXITY_API_KEY")
        if not api_key:
            print("⚠️ WARNING: PERPLEXITY_API_KEY no está configurada en las variables de entorno!")
        self.client = AsyncPerplexity()

    async def get_daily_actor_summary(self, actor_name: str) -> Dict[str, Any]:
        """Realiza una búsqueda y resumen diario sobre un actor político."""
        print(f"🔍 Iniciando resumen diario para: {actor_name}")

        analysis_prompt = f"""
Realiza una búsqueda automatizada enfocada, extrayendo y resumiendo las **notas y principales publicaciones del día** 
sobre el actor político "{actor_name}" en medios digitales, prensa y redes sociales (Facebook, Instagram, X, blogs, etc.), 
tanto a nivel nacional como estatal. Limítate a las 5-10 notas o publicaciones más relevantes y recientes de las últimas 24 horas.

Presenta los resultados en el siguiente formato JSON:

{{
  "resumen_diario_express": "Sintetiza en máximo 3 líneas las tendencias, hechos y menciones clave...",
  "registro_de_evidencia": [
    {{
      "descripcion": "Breve descripción de la nota/publicación",
      "fecha": "YYYY-MM-DD",
      "tipo_de_medio": "Prensa/Twitter/Facebook/etc",
      "link": "URL público"
    }}
  ]
}}

Prioriza velocidad y relevancia, omite duplicados y enfócate únicamente en hechos/narrativas del día.
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar",  # ✅ CAMBIO: Modelo válido
                messages=[
                    {"role": "system", "content": "Eres un analista político que responde en JSON estructurado."},
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={"type": "json_object"}  # ✅ CAMBIO: Simplificado
            )

            analysis_content = chat_response.choices[0].message.content
            print(f"✅ Respuesta recibida para {actor_name}")
            print(f"📄 Contenido: {analysis_content[:200]}...")

            analysis_json = json.loads(analysis_content)
            return analysis_json

        except PerplexityError as e:
            error_msg = f"Error en la API de Perplexity: {str(e)}"
            print(f"❌ {error_msg}")
            return {"error": error_msg}
        except json.JSONDecodeError as e:
            error_msg = f"Error decodificando JSON: {str(e)}"
            print(f"❌ {error_msg}")
            print(f"📄 Respuesta recibida: {analysis_content if 'analysis_content' in locals() else 'N/A'}")
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"Error inesperado: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            print(traceback.format_exc())
            return {"error": error_msg}

    async def get_weekly_actor_report(self, actor_name: str) -> Dict[str, Any]:
        """Realiza un análisis semanal integral sobre un actor político."""
        print(f"🔍 Iniciando reporte semanal para: {actor_name}")

        analysis_prompt = f"""
Realiza una búsqueda, extracción y análisis integral sobre el actor político "{actor_name}", considerando 
contenido público en medios digitales, redes sociales, prensa, columnas y blogs relevantes a nivel nacional 
y estatal, limitado a los últimos 30 días.

Organiza el resultado en formato JSON con esta estructura:

{{
  "resumen_ejecutivo": {{
    "sintesis": "Sintetiza hechos, tendencias y posicionamientos relevantes del actor",
    "metricas_clave": "Métricas de interacción: seguidores, comentarios, likes, menciones, cobertura mediática"
  }},
  "analisis_estrategico": {{
    "narrativas_clave": "Resume narrativas clave, posicionamientos, controversias y alianzas",
    "actores_y_temas": "Extrae actores aliados/rivales y temas recurrentes",
    "analisis_foda": {{
      "fortalezas": ["Lista de fortalezas con respaldo en evidencia"],
      "oportunidades": ["Lista de oportunidades"],
      "debilidades": ["Lista de debilidades"],
      "amenazas": ["Lista de amenazas"]
    }}
  }},
  "log_de_evidencia": [
    {{
      "descripcion": "Breve descripción/contexto",
      "fecha": "YYYY-MM-DD",
      "tipo_de_medio": "Prensa/Twitter/Facebook/etc",
      "link": "URL público"
    }}
  ]
}}

Incluye hasta 20 registros en log_de_evidencia, priorizando extracción mixta (prensa y redes sociales).
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar",  # ✅ CAMBIO: Modelo válido
                messages=[
                    {"role": "system", "content": "Eres un asistente de investigación política que responde en JSON estructurado."},
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={"type": "json_object"}  # ✅ CAMBIO: Simplificado
            )

            analysis_content = chat_response.choices[0].message.content
            print(f"✅ Reporte semanal recibido para {actor_name}")
            print(f"📄 Tamaño de respuesta: {len(analysis_content)} caracteres")

            analysis_json = json.loads(analysis_content)
            return analysis_json

        except PerplexityError as e:
            error_msg = f"Error en la API de Perplexity: {str(e)}"
            print(f"❌ {error_msg}")
            return {"error": error_msg}
        except json.JSONDecodeError as e:
            error_msg = f"Error decodificando JSON: {str(e)}"
            print(f"❌ {error_msg}")
            print(f"📄 Respuesta recibida: {analysis_content if 'analysis_content' in locals() else 'N/A'}")
            return {"error": error_msg}
        except Exception as e:
            error_msg = f"Error inesperado: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            print(traceback.format_exc())
            return {"error": error_msg}

    async def search_and_analyze(
        self, 
        query: str, 
        campaign_name: str, 
        start_date: Optional[str] = None, 
        end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Busca y analiza artículos de noticias."""
        print(f"🔍 Iniciando búsqueda para: {campaign_name}")
        print(f"📅 Rango de fechas: {start_date} a {end_date}")

        formatted_start = to_mmddyyyy(start_date)
        formatted_end = to_mmddyyyy(end_date)

        try:
            search_params = {
                "query": query,
                "max_results": 15,
            }
            if formatted_start:
                search_params["search_after_date_filter"] = formatted_start
            if formatted_end:
                search_params["search_before_date_filter"] = formatted_end

            search_results = await self.client.search.create(**search_params)
            print(f"✅ Búsqueda completada: {len(search_results.results)} resultados")

        except PerplexityError as e:
            print(f"❌ Error en búsqueda de Perplexity: {e}")
            return []
        except Exception as e:
            print(f"❌ Error inesperado en búsqueda: {e}")
            import traceback
            print(traceback.format_exc())
            return []

        analyzed_articles = []
        for idx, result in enumerate(search_results.results, 1):
            try:
                print(f"📄 Procesando artículo {idx}/{len(search_results.results)}: {result.title[:50]}...")
                
                content = await _get_url_content(result.url)
                if not content:
                    print(f"⚠️ No se pudo obtener contenido de {result.url}")
                    continue

                analysis_prompt = f"""
Analiza el siguiente texto sobre política mexicana.
Si '{campaign_name}' NO tiene relevancia, responde solo {{}}
Si SÍ es relevante, responde con este objeto JSON:

{{
  "summary": "resumen conciso (2-3 frases)",
  "sentiment_label": "Positivo|Negativo|Neutral",
  "sentiment_score": 0.5,
  "topics": ["tema1", "tema2", "tema3"],
  "key_points": ["punto clave 1", "punto clave 2"]
}}

Texto (primeros 4000 caracteres):
{content[:4000]}

Responde SOLO con el objeto JSON, sin texto adicional.
"""

                chat_response = await self.client.chat.completions.create(
                    model="sonar",  # ✅ CAMBIO: Modelo válido
                    messages=[
                        {"role": "system", "content": "Eres un analista que responde solo con objetos JSON."},
                        {"role": "user", "content": analysis_prompt},
                    ],
                    response_format={"type": "json_object"}  # ✅ CAMBIO: Simplificado
                )

                analysis_content = chat_response.choices[0].message.content
                
                # Intenta extraer JSON de la respuesta
                json_match = re.search(r"({.*})", analysis_content, re.DOTALL)
                if not json_match:
                    print(f"⚠️ No se encontró JSON en respuesta para {result.url}")
                    continue

                only_json = json_match.group(1)
                analysis_json = json.loads(only_json)
                
                # Si el JSON está vacío, el artículo no es relevante
                if not analysis_json:
                    print(f"⚠️ Artículo no relevante: {result.url}")
                    continue

                analyzed_articles.append({
                    "title": result.title,
                    "url": result.url,
                    "publishedAt": getattr(result, "publishedAt", None),
                    **analysis_json
                })
                
                print(f"✅ Artículo analizado exitosamente")

            except Exception as e:
                print(f"❌ Error procesando {result.url}: {e}")
                continue

        print(f"✅ Análisis completado: {len(analyzed_articles)} artículos procesados")
        return analyzed_articles

# Instancia del servicio
perplexity_service = PerplexityService()