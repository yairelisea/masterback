# app/services/llm.py
import os
from typing import Any, Dict
from openai import OpenAI

_client = None

def get_openai() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY no está configurada")
        _client = OpenAI(api_key=api_key)
    return _client

NEWS_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "name": "NewsAnalysis",
    "schema": {
        "type": "object",
        "properties": {
            "sentiment": {"type": "number", "minimum": -1, "maximum": 1},
            "tone": {"type": "string", "enum": ["neutral", "positive", "negative", "mixed"]},
            "topics": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
            "summary": {"type": "string", "maxLength": 1000},
            "entities": {
                "type": "object",
                "properties": {
                    "people": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                    "orgs": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                    "locations": {"type": "array", "items": {"type": "string"}, "maxItems": 10}
                },
                "required": ["people", "orgs", "locations"],
                "additionalProperties": False
            },
            "stance": {
                "type": "string",
                "description": "Postura del medio/nota hacia el actor consultado",
                "enum": ["favorable", "neutral", "crítica", "incierta"]
            }
        },
        "required": ["sentiment", "tone", "topics", "summary", "entities", "stance"],
        "additionalProperties": False
    },
    "strict": True
}

SYSTEM_PROMPT = (
    "Eres un analista de noticias en español. "
    "Analiza el título y el resumen de una nota y produce: sentimiento [-1..1], "
    "tono, 3-8 temas, resumen en 2-3 frases, entidades (personas, organizaciones, lugares) "
    "y la postura hacia el actor político consultado. Sé conciso y fiel al texto dado."
)

def analyze_snippet(title: str, summary: str, actor: str) -> Dict[str, Any]:
    """
    Usa OpenAI Responses API con Structured Outputs para regresar un JSON válido del análisis.
    """
    client = get_openai()

    prompt = (
        f"Actor político de interés: {actor}\n\n"
        f"Título: {title}\n"
        f"Resumen: {summary or '(sin resumen)'}\n"
    )

    resp = client.responses.create(
      model="gpt-5-mini",
      input=[{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": prompt}],
      response_format={
        "type": "json_schema",
        "json_schema": NEWS_ANALYSIS_SCHEMA
      },
      temperature=0.2,
    )
    # Responses API: texto directo
    return resp.output_json  # dict ya parseado