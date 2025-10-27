from __future__ import annotations
import os
import httpx
import json
import re
from typing import List, Dict, Any, Optional
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

def nombre_variantes(nombre: str) -> List[str]:
    # Puedes expandir esta lista para cada político
    nombres = [
        nombre,
        "Olga Sosa Ruiz",
        "Sosa Ruiz",
        "Olga Patricia Sosa",
        "Sosa",
        "Olga Sosa",
        # Agrega apodos/motes si los hay
    ]
    return [n.lower() for n in nombres]

class PerplexityService:
    """
    Servicio para interactuar con la API de Perplexity para búsqueda y análisis de noticias.
    """

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

        variantes = nombre_variantes(campaign_name)

        try:
            # Búsqueda
            search_params = {
                "query": query,
                "max_results": 10,
            }
            if start_date:
                search_params["search_after_date_filter"] = start_date
            if end_date:
                search_params["search_before_date_filter"] = end_date

            search_results = await self.client.search.create(**search_params)
        except PerplexityError as e:
            print(f"Error en la API de Búsqueda de Perplexity: {e}")
            return []

        analyzed_articles = []
        for result in search_results.results:
            try:
                # Get article content
                content = await _get_url_content(result.url)
                if not content:
                    continue

                # Nuevo filtro: solo descarta si ninguna variante de nombre aparece
                if not any(re.search(rf"\b{re.escape(v)}\b", content.lower()) for v in variantes):
                    # Puedes loguear pero sigue pasando al análisis
                    print(f"Posible irrelevancia {result.url}, pero se analizará con IA.")
                
                # Prompt mejorado: permite que IA decida si el actor es relevante
                analysis_prompt = f"""
                Analiza el siguiente texto sobre política mexicana. Si '{campaign_name}' NO tiene relevancia (no aparece como tema principal ni es citado), devuelve un objeto JSON vacío. Si SÍ es relevante, responde con la siguiente estructura JSON:

                1.  `summary`: Un resumen conciso (2-3 frases)
                2.  `sentiment_label`: "Positivo", "Negativo" o "Neutral"
                3.  `sentiment_score`: de -1.0 a 1.0
                4.  `topics`: 3-5 temas principales
                5.  `key_points`: 2-3 citas o puntos clave

                Texto:
                ```
                {content[:4000]}
                ```
                Responde solo con el objeto JSON.
                """

                chat_response = await self.client.chat.completions.create(
                    model="sonar-medium-online", # o el más reciente
                    messages=[
                        {"role": "system", "content": "Eres un analista de medios que responde solo con objetos JSON."},
                        {"role": "user", "content": analysis_prompt},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "summary": {"type": "string", "description": "Un resumen conciso de la noticia (2-3 frases)."},
                                    "sentiment_label": {"type": "string", "enum": ["Positivo", "Negativo", "Neutral"], "description": "El sentimiento general de la noticia hacia el actor político."},
                                    "sentiment_score": {"type": "number", "description": "Un puntaje de sentimiento de -1.0 a 1.0 con respecto al actor político."},
                                    "topics": {"type": "array", "items": {"type": "string"}, "description": "Una lista de 3 a 5 temas o palabras clave principales de la noticia."},
                                    "key_points": {"type": "array", "items": {"type": "string"}, "description": "Una lista de 2 a 3 puntos clave o citas directas de la noticia que sean más relevantes para el actor político."}
                                },
                                "required": ["summary", "sentiment_label", "sentiment_score", "topics", "key_points"]
                            }
                        }
                    },
                )

                analysis_content = chat_response.choices[0].message.content
                # Solo incluye si el análisis NO es vacío
                if analysis_content.strip() and analysis_content.strip() != "{}":
                    analysis_json = json.loads(analysis_content)
                    analyzed_articles.append({
                        "title": result.title,
                        "url": result.url,
                        "publishedAt": None,
                        **analysis_json
                    })

            except Exception as e:
                print(f"Error procesando el artículo {result.url}: {e}")
                continue

        print(f"Análisis completado. Se procesaron {len(analyzed_articles)} artículos.")
        return analyzed_articles

# Instancia del servicio para ser usada en otras partes de la aplicación
perplexity_service = PerplexityService()
