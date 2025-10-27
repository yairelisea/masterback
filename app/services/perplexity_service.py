from __future__ import annotations
import os
import httpx
import json
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from perplexity import AsyncPerplexity, PerplexityError

async def _get_url_content(url: str) -> str:
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
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%m/%d/%Y")
    except Exception as e:
        print(f"Error formateando la fecha: {e}")
        return date_str

class PerplexityService:
    def __init__(self):
        self.client = AsyncPerplexity()

    async def search_and_analyze(
        self, 
        query: str, 
        campaign_name: str, 
        start_date: Optional[str] = None,  # 'YYYY-MM-DD'
        end_date: Optional[str] = None    # 'YYYY-MM-DD'
    ) -> List[Dict[str, Any]]:
        print(f"Iniciando búsqueda y análisis para la campaña: {campaign_name} con la consulta: {query}")

        # Fechas en formato correcto
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

            search_results = await self.client.search.create(
                model="sonar-pro",  # modelo correcto para búsqueda
                **search_params
            )
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
Si '{campaign_name}' NO tiene relevancia (no aparece como tema principal ni es citado), devuelve un objeto JSON vacío: {{}}
Si SÍ es relevante, responde con el siguiente objeto JSON:
- summary: resumen conciso (2-3 frases)
- sentiment_label: "Positivo", "Negativo" o "Neutral"
- sentiment_score: de -1.0 a 1.0
- topics: 3-5 temas principales
- key_points: 2-3 citas o puntos clave

Texto:
{content[:4000]}

Responde solo con el objeto JSON.
"""

                chat_response = await self.client.chat.completions.create(
                    model="sonar-reasoning",  # modelo correcto para análisis
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
                if analysis_content.strip() and analysis_content.strip() != "{}":
                    analysis_json = json.loads(analysis_content)
                    analyzed_articles.append({
                        "title": result.title,
                        "url": result.url,
                        "publishedAt": getattr(result, "publishedAt", None),
                        **analysis_json
                    })
            except Exception as e:
                print(f"Error procesando el artículo {result.url}: {e}")
                continue

        print(f"Análisis completado. Se procesaron {len(analyzed_articles)} artículos.")
        return analyzed_articles

# Instancia de servicio
perplexity_service = PerplexityService()
