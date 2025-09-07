# app/routers/reports.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from typing import Any, Dict
import io
import os

# Usa SIEMPRE el mismo nombre que implementaste en services/report.py
# Debe devolver bytes (contenido PDF)
from app.services.report import generate_best_effort_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/pdf/{campaign_id}")
async def get_report(campaign_id: str):
    """
    Descarga un PDF ya generado previamente y guardado en /tmp/<campaign_id>.pdf
    (opcional, sólo si decides persistir archivos en disco).
    """
    file_path = f"/tmp/{campaign_id}.pdf"
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=f"{campaign_id}.pdf",
    )


@router.post("/pdf")
async def post_report(payload: Dict[str, Any]):
    """
    Recibe directamente los datos ya analizados y genera un PDF al vuelo.
    No recalcula análisis.

    Espera:
    {
      "campaign": { "name": "...", "query": "...", ... },
      "analysis": {
        "summary": "...",
        "sentiment_label": "...",
        "sentiment_score": 0.23,
        "sentiment_score_pct": 61,   # opcional
        "topics": [...],
        "items": [
          {
            "title": "...",
            "url": "...",
            "source": "...",
            "llm": {
              "summary": "...",
              "sentiment_label": "...",
              "sentiment_score": 0.12,
              "sentiment_score_pct": 56
            }
          },
          ...
        ]
      }
    }
    """
    try:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="JSON inválido")

        campaign = payload.get("campaign") or {}
        analysis = payload.get("analysis") or {}

        if not analysis:
            raise HTTPException(status_code=400, detail="El campo 'analysis' es requerido")

        # Genera bytes PDF (services/report.py debe retornarlos)
        pdf_bytes: bytes = generate_best_effort_report(campaign=campaign, analysis=analysis)

        filename = (campaign.get("name") or campaign.get("query") or "Reporte") + ".pdf"
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")