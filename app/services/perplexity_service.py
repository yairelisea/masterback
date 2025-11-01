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
            print("⚠️ WARNING: PERPLEXITY_API_KEY no está configurada!")
        self.client = AsyncPerplexity()

    async def get_daily_actor_summary(self, actor_name: str) -> Dict[str, Any]:
        """Realiza una búsqueda y resumen diario sobre un actor político."""
        print(f"🔍 Iniciando resumen diario para: {actor_name}")

        analysis_prompt = f"""
Eres un analista político. Realiza una búsqueda sobre el actor político "{actor_name}" en las últimas 24 horas.

IMPORTANTE: Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional antes o después. No uses markdown ni backticks.

Estructura requerida:
{{
  "resumen_diario_express": "Sintetiza en máximo 3 líneas las tendencias, hechos y menciones clave del último día",
  "registro_de_evidencia": [
    {{
      "descripcion": "Breve descripción de la nota o publicación",
      "fecha": "YYYY-MM-DD",
      "tipo_de_medio": "Prensa/Twitter/Facebook/Instagram/Blog/etc",
      "link": "URL completa"
    }}
  ]
}}

Incluye entre 5 y 10 entradas en registro_de_evidencia mezclando prensa y redes sociales.
Responde SOLO con el JSON, sin texto adicional.
"""

        try:
            # SIN response_format - Perplexity no lo soporta como OpenAI
            chat_response = await self.client.chat.completions.create(
                model="sonar",
                messages=[
                    {"role": "system", "content": "Eres un analista político que responde exclusivamente en formato JSON válido."},
                    {"role": "user", "content": analysis_prompt},
                ]
            )

            analysis_content = chat_response.choices[0].message.content
            print(f"✅ Respuesta recibida para {actor_name}")
            print(f"📄 Primeros 300 caracteres: {analysis_content[:300]}")

            # Extraer JSON de la respuesta (puede venir con texto adicional)
            json_match = re.search(r'\{[\s\S]*\}', analysis_content)
            if not json_match:
                print(f"⚠️ No se encontró JSON en la respuesta")
                return {
                    "error": "La IA no devolvió un formato JSON válido",
                    "raw_response": analysis_content[:500]
                }

            json_str = json_match.group(0)
            analysis_json = json.loads(json_str)
            return analysis_json

        except PerplexityError as e:
            error_msg = f"Error en la API de Perplexity: {str(e)}"
            print(f"❌ {error_msg}")
            return {"error": error_msg}
        except json.JSONDecodeError as e:
            error_msg = f"Error decodificando JSON: {str(e)}"
            print(f"❌ {error_msg}")
            if 'analysis_content' in locals():
                print(f"📄 Respuesta completa: {analysis_content}")
            return {"error": error_msg, "raw_response": locals().get('analysis_content', 'N/A')[:500]}
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
Eres un analista político estratégico. Realiza un análisis integral sobre el actor político "{actor_name}" de los últimos 30 días.

IMPORTANTE: Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional antes o después. No uses markdown ni backticks.

Estructura requerida:
{{
  "resumen_ejecutivo": {{
    "sintesis": "Sintetiza hechos, tendencias y posicionamientos relevantes del actor en los últimos 30 días",
    "metricas_clave": "Métricas de interacción: seguidores, comentarios, likes, menciones, cobertura mediática, eventos"
  }},
  "analisis_estrategico": {{
    "narrativas_clave": "Resume narrativas principales, posicionamientos, controversias y alianzas a nivel nacional y estatal",
    "actores_y_temas": "Identifica actores aliados/rivales y temas recurrentes en la conversación política",
    "analisis_foda": {{
      "fortalezas": ["Fortaleza 1 con evidencia", "Fortaleza 2 con evidencia"],
      "oportunidades": ["Oportunidad 1", "Oportunidad 2"],
      "debilidades": ["Debilidad 1", "Debilidad 2"],
      "amenazas": ["Amenaza 1", "Amenaza 2"]
    }}
  }},
  "log_de_evidencia": [
    {{
      "descripcion": "Descripción breve de la publicación o nota",
      "fecha": "YYYY-MM-DD",
      "tipo_de_medio": "Prensa/Twitter/Facebook/Instagram/Blog/Columna/etc",
      "link": "URL completa"
    }}
  ]
}}

Incluye hasta 20 registros en log_de_evidencia, mezclando prensa y redes sociales.
Prioriza información no duplicada y momentos relevantes del actor.
Responde SOLO con el JSON, sin texto adicional.
"""

        try:
            # SIN response_format - Perplexity no lo soporta como OpenAI
            chat_response = await self.client.chat.completions.create(
                model="sonar",
                messages=[
                    {"role": "system", "content": "Eres un analista político estratégico que responde exclusivamente en formato JSON válido."},
                    {"role": "user", "content": analysis_prompt},
                ]
            )

            analysis_content = chat_response.choices[0].message.content
            print(f"✅ Reporte semanal recibido para {actor_name}")
            print(f"📄 Tamaño de respuesta: {len(analysis_content)} caracteres")

            # Extraer JSON de la respuesta
            json_match = re.search(r'\{[\s\S]*\}', analysis_content)
            if not json_match:
                print(f"⚠️ No se encontró JSON en la respuesta")
                return {
                    "error": "La IA no devolvió un formato JSON válido",
                    "raw_response": analysis_content[:500]
                }

            json_str = json_match.group(0)
            analysis_json = json.loads(json_str)
            return analysis_json

        except PerplexityError as e:
            error_msg = f"Error en la API de Perplexity: {str(e)}"
            print(f"❌ {error_msg}")
            return {"error": error_msg}
        except json.JSONDecodeError as e:
            error_msg = f"Error decodificando JSON: {str(e)}"
            print(f"❌ {error_msg}")
            if 'analysis_content' in locals():
                print(f"📄 Respuesta completa: {analysis_content}")
            return {"error": error_msg, "raw_response": locals().get('analysis_content', 'N/A')[:500]}
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
                print(f"📄 Procesando {idx}/{len(search_results.results)}: {result.title[:50]}...")
                
                content = await _get_url_content(result.url)
                if not content:
                    print(f"⚠️ No se pudo obtener contenido de {result.url}")
                    continue

                analysis_prompt = f"""
Analiza si el siguiente texto es relevante para '{campaign_name}'.

IMPORTANTE: Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional. No uses markdown ni backticks.

Si NO es relevante, responde: {{}}
Si SÍ es relevante, responde:
{{
  "summary": "Resumen conciso en 2-3 frases",
  "sentiment_label": "Positivo" o "Negativo" o "Neutral",
  "sentiment_score": 0.5,
  "topics": ["tema1", "tema2", "tema3"],
  "key_points": ["punto clave 1", "punto clave 2"]
}}

Texto a analizar (primeros 4000 caracteres):
{content[:4000]}

Responde SOLO con el JSON, sin texto adicional.
"""

                # SIN response_format
                chat_response = await self.client.chat.completions.create(
                    model="sonar",
                    messages=[
                        {"role": "system", "content": "Eres un analista que responde exclusivamente en formato JSON válido."},
                        {"role": "user", "content": analysis_prompt},
                    ]
                )

                analysis_content = chat_response.choices[0].message.content
                
                # Extraer JSON
                json_match = re.search(r'\{[\s\S]*?\}', analysis_content)
                if not json_match:
                    print(f"⚠️ No se encontró JSON en respuesta para {result.url}")
                    continue

                json_str = json_match.group(0)
                analysis_json = json.loads(json_str)
                
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

            except json.JSONDecodeError as e:
                print(f"❌ Error parseando JSON para {result.url}: {e}")
                if 'analysis_content' in locals():
                    print(f"📄 Respuesta: {analysis_content[:200]}")
                continue
            except Exception as e:
                print(f"❌ Error procesando {result.url}: {e}")
                continue

        print(f"✅ Análisis completado: {len(analyzed_articles)} artículos procesados")
        return analyzed_articles

# Instancia del servicio
perplexity_service = PerplexityService()