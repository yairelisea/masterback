# app/services/llm.py
import os
from typing import Any, Dict, List
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

# ---------- JSON Schemas para Structured Outputs ----------
NEWS_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "name": "NewsAnalysis",
    "schema": {
        "type": "object",
        "properties": {
            "sentiment": {"type": "number", "minimum": -1, "maximum": 1},
            "tone": {"type": "string", "enum": ["neutral", "positive", "negative", "mixed"]},
            "topics": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 10},
            "summary": {"type": "string", "maxLength": 800},
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
                "description": "Postura del contenido hacia el actor consultado",
                "enum": ["favorable", "neutral", "crítica", "incierta"]
            },
            "perception": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "Cómo queda percibido el político en esta nota (máx. 3–5 frases).",
                        "maxLength": 600
                    },
                    "evidence": {
                        "type": "array",
                        "description": "Puntos concretos de la nota que sustentan la percepción.",
                        "items": {"type": "string"},
                        "maxItems": 5
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0, "maximum": 1,
                        "description": "Confianza del análisis dado el texto disponible."
                    }
                },
                "required": ["view", "evidence", "confidence"],
                "additionalProperties": False
            }
        },
        "required": ["sentiment", "tone", "topics", "summary", "entities", "stance", "perception"],
        "additionalProperties": False
    },
    "strict": True
}

AGGREGATE_SCHEMA: Dict[str, Any] = {
    "name": "AggregateNewsPerspective",
    "schema": {
        "type": "object",
        "properties": {
            "overall_sentiment": {"type": "number", "minimum": -1, "maximum": 1},
            "stance_distribution": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "favorable": {"type": "integer", "minimum": 0},
                    "neutral": {"type": "integer", "minimum": 0},
                    "crítica": {"type": "integer", "minimum": 0},
                    "incierta": {"type": "integer", "minimum": 0}
                },
                "required": ["favorable", "neutral", "crítica", "incierta"]
            },
            "top_topics": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
            "key_takeaways": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
            "perception_overview": {
                "type": "string",
                "description": "Síntesis narrativa de la percepción del político en el periodo.",
                "maxLength": 1000
            }
        },
        "required": ["overall_sentiment", "stance_distribution", "top_topics", "key_takeaways", "perception_overview"],
        "additionalProperties": False
    },
    "strict": True
}

SYSTEM_PROMPT_ITEM = (
    "Eres un analista de noticias en español. "
    "Analiza el título y el resumen de una nota y produce: "
    "sentimiento [-1..1], tono, 3-8 temas, resumen (2-3 frases), "
    "entidades (personas/organizaciones/lugares), postura hacia el actor, "
    "y una PERCEPCIÓN (párrafo breve) con evidencia y confianza. "
    "Sé fiel al texto disponible y evita inventar información."
)

SYSTEM_PROMPT_AGG = (
    "Eres un consultor político. Con base en una lista de resultados ya analizados "
    "(título, fuente, fecha, y un JSON con sentimiento, temas, postura y percepción), "
    "crea una síntesis ejecutiva: promedio de sentimiento, distribución de posturas, "
    "temas predominantes, 3-6 conclusiones y una perspectiva general de cómo se percibe "
    "al actor político en el periodo."
)

def analyze_snippet(title: str, summary: str, actor: str) -> Dict[str, Any]:
    """Analiza una sola nota (título + resumen) y devuelve JSON estructurado."""
    client = get_openai()
    prompt = (
        f"Actor político de interés: {actor}\n\n"
        f"Título: {title}\n"
        f"Resumen: {summary or '(sin resumen)'}\n"
    )
    resp = client.responses.create(
        model="gpt-5-mini",
        input=[{"role": "system", "content": SYSTEM_PROMPT_ITEM},
               {"role": "user", "content": prompt}],
        response_format={"type": "json_schema", "json_schema": NEWS_ANALYSIS_SCHEMA},
        temperature=0.2,
    )
    return resp.output_json

def aggregate_perspective(actor: str, analyzed_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Recibe una lista con:
    { title, source, published_at (ISO opcional), llm (JSON de NewsAnalysis) }
    y devuelve una síntesis agregada.
    """
    client = get_openai()

    compact: List[Dict[str, Any]] = []
    for it in analyzed_items:
        llm = it.get("llm", {})
        compact.append({
            "title": it.get("title"),
            "source": it.get("source"),
            "published_at": it.get("published_at"),
            "sentiment": llm.get("sentiment"),
            "tone": llm.get("tone"),
            "topics": llm.get("topics", []),
            "stance": llm.get("stance"),
            "perception": llm.get("perception", {})
        })

    prompt = (
        f"Actor político: {actor}\n\n"
        f"Entradas:\n{compact}\n\n"
        "Genera una visión agregada sólida."
    )

    resp = client.responses.create(
        model="gpt-5-mini",
        input=[{"role": "system", "content": SYSTEM_PROMPT_AGG},
               {"role": "user", "content": prompt}],
        response_format={"type": "json_schema", "json_schema": AGGREGATE_SCHEMA},
        temperature=0.2,
    )
    return resp.output_json