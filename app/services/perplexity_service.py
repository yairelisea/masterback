
from __future__ import annotations
import os
import httpx
import json
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
            # Aquí se podría usar una librería como BeautifulSoup para extraer solo el texto principal
            # Por simplicidad, usaremos el texto completo, pero esto puede ser muy ruidoso
            return resp.text
    except Exception as e:
        print(f"Error al obtener contenido de {url}: {e}")
        return ""

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
        """
        Realiza una búsqueda en Perplexity y luego analiza cada resultado usando la API de Chat.
        """
        print(f"Iniciando búsqueda y análisis para la campaña: {campaign_name} con la consulta: {query}")
        
        try:
            # 1. Buscar artículos con la API de Búsqueda
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
                # 2. Para cada artículo, obtener el contenido de la URL
                # Nota: esto puede ser lento y propenso a errores (bloqueos, contenido dinámico, etc.)
                content = await _get_url_content(result.url)
                if not content:
                    continue

                # 3. Analizar el contenido con la API de Chat
                analysis_prompt = f"""
                Analiza el siguiente texto de una noticia y extrae la siguiente información en formato JSON:
                1.  `summary`: Un resumen conciso de la noticia (2-3 frases).
                2.  `sentiment_label`: El sentimiento general de la noticia. Debe ser uno de: "Positivo", "Negativo", "Neutral".
                3.  `sentiment_score`: Un puntaje de sentimiento de -1.0 (muy negativo) a 1.0 (muy positivo).
                4.  `topics`: Una lista de 3 a 5 temas o palabras clave principales.

                Texto de la noticia:
                ```
                {content[:4000]}  # Limitar a ~4k caracteres para no exceder el límite de tokens
                ```

                Responde únicamente con el objeto JSON.
                """

                chat_response = await self.client.chat.completions.create(
                    model="pplx-70b-online",
                    messages=[
                        {"role": "system", "content": "Eres un asistente de análisis de medios que solo responde con JSON."},
                        {"role": "user", "content": analysis_prompt},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "summary": {"type": "string", "description": "Un resumen conciso de la noticia (2-3 frases)."},
                                    "sentiment_label": {"type": "string", "enum": ["Positivo", "Negativo", "Neutral"], "description": "El sentimiento general de la noticia."},
                                    "sentiment_score": {"type": "number", "description": "Un puntaje de sentimiento de -1.0 a 1.0."},
                                    "topics": {"type": "array", "items": {"type": "string"}, "description": "Una lista de 3 a 5 temas o palabras clave principales."}
                                },
                                "required": ["summary", "sentiment_label", "sentiment_score", "topics"]
                            }
                        }
                    },
                )

                analysis_content = chat_response.choices[0].message.content
                analysis_json = json.loads(analysis_content)

                # 4. Combinar los resultados
                analyzed_articles.append({
                    "title": result.title,
                    "url": result.url,
                    "publishedAt": None,  # La API de búsqueda no provee esta información
                    "summary": analysis_json.get("summary"),
                    "sentiment_score": analysis_json.get("sentiment_score"),
                    "sentiment_label": analysis_json.get("sentiment_label"),
                    "topics": analysis_json.get("topics"),
                })

            except Exception as e:
                print(f"Error procesando el artículo {result.url}: {e}")
                continue
        
        print(f"Análisis completado. Se procesaron {len(analyzed_articles)} artículos.")
        return analyzed_articles

# Instancia del servicio para ser usada en otras partes de la aplicación
perplexity_service = PerplexityService()
