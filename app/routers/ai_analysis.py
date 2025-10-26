from __future__ import annotations

from fastapi import APIRouter, Query, Header, HTTPException, Request
from typing import Any, Dict, List, Optional
import datetime as dt

# Importar el servicio de Perplexity
from ..services.perplexity_service import perplexity_service

router = APIRouter(prefix="/ai", tags=["ai"])

# -----------------------------------------------------------------------------------
# Endpoint principal
# -----------------------------------------------------------------------------------

@router.get("/analyze-news")
async def analyze_news(
    request: Request,
    q: str = Query(..., description="Consulta (ej. nombre del actor político)"),
    size: int = Query(35, ge=1, le=100), # Este parámetro ya no se usa directamente en la búsqueda de Perplexity
    days_back: int = Query(30, ge=1, le=60),
    lang: str = Query("es-419"), # Parámetro no utilizado por Perplexity de esta forma
    country: str = Query("MX"), # Parámetro no utilizado por Perplexity de esta forma
    overall: bool = Query(True, description="Si true, devuelve resumen agregado (funcionalidad no disponible con Perplexity)"),
    userId: Optional[str] = None,
    x_user_id: Optional[str] = Header(default=None),
):
    """
    1) Busca y analiza noticias usando el servicio de Perplexity.
    2) Devuelve los resultados analizados.
    """
    effective_user = x_user_id or userId or "anonymous"

    # Calcular fechas para la búsqueda en Perplexity
    end_date_dt = dt.datetime.utcnow()
    start_date_dt = end_date_dt - dt.timedelta(days=days_back)
    
    # Formato de fecha para la API de Perplexity: %m/%d/%Y
    start_date_str_api = start_date_dt.strftime("%m/%d/%Y")
    end_date_str_api = end_date_dt.strftime("%m/%d/%Y")

    # Formato de fecha para el query string: YYYY-MM-DD
    start_date_str_query = start_date_dt.strftime("%Y-%m-%d")
    end_date_str_query = end_date_dt.strftime("%Y-%m-%d")

    # Añadir filtros de fecha a la consulta
    q_with_dates = f"{q} after:{start_date_str_query} before:{end_date_str_query}"

    try:
        # Llamar al servicio de Perplexity
        analyzed_articles = await perplexity_service.search_and_analyze(
            query=q_with_dates,
            campaign_name=q,  # Usando la query original como nombre de campaña
            start_date=start_date_str_api,
            end_date=end_date_str_api,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el servicio de Perplexity: {e}")

    if not analyzed_articles:
        return {
            "overall": {
                "summary": "No se encontraron notas en el periodo solicitado.",
                "sentiment_label": None,
                "sentiment_score": None,
                "topics": [],
                "perception": {},
            },
            "items": [],
            "meta": {"q": q, "size": size, "days_back": days_back, "lang": lang, "country": country},
        }

    # El servicio de Perplexity ya devuelve los items analizados.
    # La funcionalidad "overall" no está implementada en el nuevo servicio.
    overall_block = {
        "summary": "El resumen general no está disponible en esta versión.",
        "sentiment_label": None,
        "sentiment_score": None,
        "topics": [],
        "perception": {},
    }

    return {
        "overall": overall_block,
        "items": analyzed_articles,
        "meta": {
            "q": q,
            "size": size,
            "days_back": days_back,
            "lang": lang,
            "country": country,
            "user": effective_user,
        },
    }