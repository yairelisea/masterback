# app/services/llm.py
import os, json
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
                        "description": "Cómo queda percibido el político en esta nota (3–5 frases).",
                        "maxLength": 600
                    },
                    "evidence": {
                        "type": "array",
                        "description": "Puntos concretos que sustentan la percepción.",
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
    "y una PERCEPCIÓN (párrafo breve) con 2-5 evidencias y confianza. "
    "Sé fiel al texto y evita inventar información."
)

SYSTEM_PROMPT_AGG = (
    "Eres un consultor político. Con base en una lista de resultados ya analizados "
    "(título, fuente, fecha y JSON con sentimiento, temas, postura y percepción), "
    "crea una síntesis ejecutiva: promedio de sentimiento, distribución de posturas, "
    "temas predominantes, 3-6 conclusiones y una perspectiva general de cómo se percibe "
    "al actor político en el periodo."
)

def _parse_json_strict(text: str) -> Dict[str, Any]:
    """
    Intenta parsear JSON puro. Si viene texto extra, busca el primer y último '{'...'}'.
    """
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end+1])
        raise

def _chat_structured(messages: List[Dict[str, str]], schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Intenta usar json_schema; si el cliente no lo soporta, cae a json_object.
    OJO: no enviamos 'temperature' porque ciertos modelos no aceptan overrides (default=1).
    """
    client = get_openai()
    # 1) Intento: json_schema (estricto)
    try:
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            messages=messages,
            response_format={"type": "json_schema", "json_schema": schema},
            # NO temperature aquí
        )
        content = resp.choices[0].message.content or "{}"
        return _parse_json_strict(content)
    except TypeError:
        # 2) Fallback: json_object + instrucción de esquema en el mensaje del sistema
        messages_fallback = [
            {"role": "system", "content": f"{messages[0]['content']}\n\n"
                                          f"Devuelve ÚNICAMENTE un JSON válido con la forma: {json.dumps(schema['schema'])} "
                                          f"(sin ningún texto adicional)."},
            *messages[1:]
        ]
        resp = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            messages=messages_fallback,
            response_format={"type": "json_object"},
            # NO temperature aquí
        )
        content = resp.choices[0].message.content or "{}"
        return _parse_json_strict(content)

def analyze_snippet(title: str, summary: str, actor: str) -> Dict[str, Any]:
    """Analiza una sola nota (título + resumen) y devuelve JSON estructurado."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_ITEM},
        {"role": "user", "content": (
            f"Actor político de interés: {actor}\n\n"
            f"Título: {title}\n"
            f"Resumen: {summary or '(sin resumen)'}\n"
        )},
    ]
    return _chat_structured(messages, NEWS_ANALYSIS_SCHEMA)

def aggregate_perspective(actor: str, analyzed_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Recibe una lista con:
    { title, source, published_at (ISO opcional), llm (JSON de NewsAnalysis) }
    y devuelve una síntesis agregada.
    """
    # Compactamos entrada
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

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_AGG},
        {"role": "user", "content": (
            f"Actor político: {actor}\n\n"
            f"Entradas (compactas):\n{json.dumps(compact, ensure_ascii=False)}\n\n"
            "Genera una visión agregada sólida."
        )},
    ]
    return _chat_structured(messages, AGGREGATE_SCHEMA)