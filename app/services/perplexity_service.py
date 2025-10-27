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