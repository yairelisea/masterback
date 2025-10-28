from __future__ import annotations
import os
import httpx
import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from perplexity import AsyncPerplexity, PerplexityError

# La clave de API se toma de las variables de entorno
# El usuario ha confirmado que PERPLEXITY_API_KEY está configurada

async def _get_url_content(url: str) -> str:
    """Obtiene el contenido de texto de una URL."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
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
    # Si ya está en MM/DD/YYYY, la deja igual
    if re.match(r"\d{2}/\d{2}/\d{4}$", date_str):
        return date_str
    # Si viene como YYYY-MM-DD, la convierte
    if re.match(r"\d{4}-\d{2}-\d{2}$", date_str):
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").strftime("%m/%d/%Y")
        except Exception as e:
            print(f"Error formateando la fecha '{date_str}': {e}")
            return None
    # Si es otro formato, intenta devolver None para forzar validación
    print(f"Formato de fecha no reconocido: '{date_str}'")
    return None

class PerplexityService:
    def __init__(self):
        self.client = AsyncPerplexity()

    async def get_daily_actor_summary(self, actor_name: str) -> Dict[str, Any]:
        """
        Realiza una búsqueda y resumen diario sobre un actor político.
        """
        print(f"Iniciando resumen diario para el actor: {actor_name}")

        analysis_prompt = f"""
Realiza una búsqueda automatizada enfocada, extrayendo y resumiendo las **notas y principales publicaciones del día** sobre el actor político "{actor_name}" en medios digitales, prensa y redes sociales (Facebook, Instagram, X, blogs, etc.), tanto a nivel nacional como estatal. Limítate a las 5-10 notas o publicaciones más relevantes y recientes de las últimas 24 horas.

Presenta los resultados en el siguiente formato JSON:

1.  **Resumen Diario Express:**
    - Sintetiza en máximo 3 líneas las tendencias, hechos y menciones clave del actor político en el periodo monitoreado (último día).

2.  **Registro de Evidencia (5-10 entradas):**
    - Enumera entre 5 y 10 notas/noticias y publicaciones del día, mezclando prensa y redes sociales, con breve descripción, fecha y link público si es posible.

Prioriza velocidad y relevancia, omite duplicados y enfócate únicamente en hechos/narrativas del día. Este informe es para monitoreo y actualización diaria, usable en dashboards o reportes express.
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Eres un asistente de investigación especializado en análisis de medios y actores políticos. Tu tarea es realizar búsquedas y presentar la information en un formato JSON estructurado y conciso, siguiendo estrictamente las instrucciones del usuario."},
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "resumen_diario_express": {
                                    "type": "string",
                                    "description": "Síntesis en máximo 3 líneas de las tendencias, hechos y menciones clave del actor político en las últimas 24 horas."
                                },
                                "registro_de_evidencia": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "descripcion": {"type": "string"},
                                            "fecha": {"type": "string"},
                                            "link": {"type": "string", "format": "uri"}
                                        },
                                        "required": ["descripcion", "fecha", "link"]
                                    },
                                    "description": "Lista de 5 a 10 notas/publicaciones relevantes con descripción, fecha y link."
                                }
                            },
                            "required": ["resumen_diario_express", "registro_de_evidencia"]
                        }
                    }
                },
            )

            analysis_content = chat_response.choices[0].message.content
            print(f"\n==RESPUESTA IA PARA {actor_name}==\n{analysis_content}\n")

            # El contenido ya debería ser un JSON válido gracias a response_format
            analysis_json = json.loads(analysis_content)
            return analysis_json

        except PerplexityError as e:
            print(f"Error en la API de Perplexity para el actor '{actor_name}': {e}")
            return {"error": str(e)}
        except json.JSONDecodeError as e:
            print(f"Error al decodificar JSON para el actor '{actor_name}': {e}")
            return {"error": "Error decodificando la respuesta JSON."}
        except Exception as e:
            print(f"Error inesperado durante el resumen para '{actor_name}': {e}")
            return {"error": "Ocurrió un error inesperado."}

    async def get_weekly_actor_report(self, actor_name: str) -> Dict[str, Any]:
        """
        Realiza un análisis semanal integral sobre un actor político.
        """
        print(f"Iniciando reporte semanal para el actor: {actor_name}")

        analysis_prompt = f"""
Realiza una búsqueda, extracción y análisis integral sobre el actor político "{actor_name}", considerando contenido público en medios digitales, redes sociales, prensa, columnas y blogs relevantes a nivel nacional y estatal, limitado a los últimos 30 días.

Organiza el resultado en tres secciones estructuradas tipo informe, en formato JSON:

1. **Resumen Ejecutivo y Métricas Clave:**
    - Sintetiza hechos, tendencias y posicionamientos relevantes del actor.
    - Incluye métricas de interacción: seguidores, comentarios, likes, menciones, cobertura mediática, participación en eventos y debates nacionales/estatales.

2. **Análisis Político, Comunicacional y FODA:**
    - Resume narrativas clave, posicionamientos, controversias y alianzas a nivel nacional y estatal.
    - Extrae actores aliados/rivales y temas recurrentes de interés en la conversación política digital y mediática.
    - Presenta FODA estratégico (Fortalezas, Oportunidades, Debilidades, Amenazas) con respaldo en evidencia digital/mediática.

3. **Log y Evidencia (20 registros mezclados):**
    - Enumera hasta 20 publicaciones relevantes: incluye tanto notas periodísticas, columnas, blogs, como posts, reels, videos y tweets públicos generados en redes sociales.
    - Incluye para cada registro: breve descripción/contexto, fecha, tipo de medio y enlace público (cuando sea posible).

Prioriza extracción mixta (prensa y RS), informaciones no duplicadas, e identifica los momentos más relevantes del actor en el último mes.
"""

        try:
            chat_response = await self.client.chat.completions.create(
                model="sonar-reasoning",
                messages=[
                    {"role": "system", "content": "Eres un asistente de investigación y análisis estratégico especializado en el sector político. Tu tarea es realizar análisis integrales y presentar la información en un formato JSON estructurado y profesional, siguiendo estrictamente las instrucciones del usuario."},
                    {"role": "user", "content": analysis_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "resumen_ejecutivo": {
                                    "type": "object",
                                    "properties": {
                                        "sintesis": {"type": "string", "description": "Síntesis de hechos, tendencias y posicionamientos relevantes del actor."},
                                        "metricas_clave": {"type": "string", "description": "Métricas de interacción: seguidores, comentarios, likes, menciones, etc."}
                                    },
                                    "required": ["sintesis", "metricas_clave"]
                                },
                                "analisis_estrategico": {
                                    "type": "object",
                                    "properties": {
                                        "narrativas_clave": {"type": "string", "description": "Narrativas, posicionamientos, controversias y alianzas."},
                                        "actores_y_temas": {"type": "string", "description": "Actores aliados/rivales y temas recurrentes."},
                                        "analisis_foda": {
                                            "type": "object",
                                            "properties": {
                                                "fortalezas": {"type": "array", "items": {"type": "string"}},
                                                "oportunidades": {"type": "array", "items": {"type": "string"}},
                                                "debilidades": {"type": "array", "items": {"type": "string"}},
                                                "amenazas": {"type": "array", "items": {"type": "string"}}
                                            },
                                            "required": ["fortalezas", "oportunidades", "debilidades", "amenazas"]
                                        }
                                    },
                                    "required": ["narrativas_clave", "actores_y_temas", "analisis_foda"]
                                },
                                "log_de_evidencia": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "descripcion": {"type": "string"},
                                            "fecha": {"type": "string"},
                                            "tipo_de_medio": {"type": "string"},
                                            "link": {"type": "string", "format": "uri"}
                                        },
                                        "required": ["descripcion", "fecha", "tipo_de_medio", "link"]
                                    },
                                    "description": "Lista de hasta 20 publicaciones relevantes (medios y redes sociales)."
                                }
                            },
                            "required": ["resumen_ejecutivo", "analisis_estrategico", "log_de_evidencia"]
                        }
                    }
                },
            )

            analysis_content = chat_response.choices[0].message.content
            print(f"\n==REPORTE SEMANAL IA PARA {actor_name}==\n{analysis_content}\n")

            analysis_json = json.loads(analysis_content)
            return analysis_json

        except PerplexityError as e:
            print(f"Error en la API de Perplexity para el reporte semanal de '{actor_name}': {e}")
            return {"error": str(e)}
        except Exception as e:
            print(f"Error inesperado durante el reporte semanal para '{actor_name}': {e}")
            return {"error": "Ocurrió un error inesperado."}

    async def search_and_analyze(
        self, 
        query: str, 
        campaign_name: str, 
        start_date: Optional[str] = None, 
        end_date: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        print(f"Iniciando búsqueda y análisis para la campaña: {campaign_name} con la consulta: {query}")

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

            # SIN model en la búsqueda
            search_results = await self.client.search.create(**search_params)
        except PerplexityError as e:
            print(f"Error en la API de Búsqueda de Perplexity: {e}")
            return []

        analyzed_articles = []
        for result in search_results.results:
            try:
                content = await _get_url_content(result.url)
                if not content:
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

text
Responde solo con el objeto JSON.
"""

                chat_response = await self.client.chat.completions.create(
                    model="sonar-reasoning",  # solo aquí se especifica el modelo!!!
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
                )

                analysis_content = chat_response.choices[0].message.content

                print(f"\n==RESPUESTA IA PARA {result.url}==\n{analysis_content}\n")

                # Extrae el primer bloque JSON, omitiendo texto extra de la IA
                json_match = re.search(r"({.*})", analysis_content, re.DOTALL)
                if not json_match:
                    print(f"No se encontró JSON en la respuesta IA para {result.url}")
                    continue

                only_json = json_match.group(1)

                try:
                    analysis_json = json.loads(only_json)
                    analyzed_articles.append({
                        "title": result.title,
                        "url": result.url,
                        "publishedAt": getattr(result, "publishedAt", None),
                        **analysis_json
                    })
                except Exception as e:
                    print(f"Error al parsear JSON para {result.url}: '{only_json}' -> {e}")
                    continue

            except Exception as e:
                print(f"Error procesando el artículo {result.url}: {e}")
                continue

        print(f"Análisis completado. Se procesaron {len(analyzed_articles)} artículos.")
        return analyzed_articles

# Instancia del servicio para ser usada en otras partes de la aplicación
perplexity_service = PerplexityService()