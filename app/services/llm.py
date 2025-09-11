from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# SDK oficial
from openai import OpenAI

# Ajusta por el modelo que tengas disponible en tu cuenta
# Si usas "gpt-4o-mini" o "gpt-3.5-turbo", cámbialo aquí:
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # o "gpt-3.5-turbo"

# Instancia del cliente, requiere OPENAI_API_KEY en el entorno
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

SYSTEM_PROMPT = """Eres un analista de medios. Resume brevemente el contenido proporcionado y evalúa:
- sentiment_label: "positivo" | "neutral" | "negativo"
- sentiment_score: número de -1.0 a 1.0
- topics: lista corta de temas clave
- stance: "a favor" | "en contra" | "neutral" respecto del actor político principal
- perception: objeto con claves: { "imagen_publica": breve, "riesgos": breve, "oportunidades": breve }

Responde en JSON válido con estas claves:
{ "summary": string, "sentiment_label": string, "sentiment_score": number, "topics": [string], "stance": string, "perception": { ... } }
No agregues texto fuera del JSON.
"""

def _coerce_json(s: str) -> Dict[str, Any]:
    """Intenta parsear la salida como JSON aunque el modelo agregue texto extra."""
    import json, re
    # Extrae el primer bloque {...}
    m = re.search(r"\{.*\}", s, flags=re.S)
    if not m:
        return {"_raw": s}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"_raw": s}

async def analyze_snippet(title: str, summary: str, actor: str) -> Dict[str, Any]:
    """
    Llama a Chat Completions con instrucciones para devolver JSON. Sin temperatura custom
    para compatibilidad con modelos que no permiten modificarla.
    """
    user_content = f"""ACTOR: {actor}
TÍTULO: {title}
RESUMEN/DATOS:
{summary}
"""

    # Si no hay API key, devolvemos un análisis neutro rápido (fallback)
    if not client:
        return {
            "summary": (title or "").strip()[:140],
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "topics": [],
            "stance": "neutral",
            "perception": {"note": "fallback (no OPENAI_API_KEY)"},
        }

    # Nota: evitamos pasar 'temperature' para evitar errores de "unsupported value"
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            # no temperature param
        )
        text = resp.choices[0].message.content or ""
        return _coerce_json(text)
    except Exception as e:
        # fallback si el proveedor falla
        return {
            "summary": (title or "").strip()[:140],
            "sentiment_label": "neutral",
            "sentiment_score": 0.0,
            "topics": [],
            "stance": "neutral",
            "perception": {"note": f"fallback (llm error: {e})"},
        }

# --- Fallback para compatibilidad con scheduler ---
from typing import List, Dict, Any

async def aggregate_perspective(
    snippets: List[Dict[str, Any]] | None,
    actor: str,
    language: str = "es",
) -> Dict[str, Any]:
    """
    Fallback sin LLM para que el scheduler no truene si no existe la función.
    Espera una lista de items con llaves como 'title' y/o 'summary'.
    Devuelve un dict tipo AIAnalysisResult parcial:
      - verdict (str | None)
      - key_points (list[str])
      - perception (dict)
    """
    texts: List[str] = []
    for it in (snippets or []):
        if isinstance(it, dict):
            t = (it.get("summary") or it.get("title") or "").strip()
            if t:
                texts.append(t)

    # Heurística mínima (sin LLM real)
    key_points = texts[:5]
    verdict = None
    perception = {
        "note": "fallback aggregator (no-LLM)",
        "actor": actor,
        "language": language,
        "count": len(texts),
    }
    return {
        "verdict": verdict,
        "key_points": key_points,
        "perception": perception,
    }
