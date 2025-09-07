# app/routers/reports.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from typing import Any, Dict
import io
import os

# Usa el generador que tengas disponible en services
# (si tu servicio se llama diferente, ajusta el import)
from app.services.report import generate_best_effort_report

router = APIRouter(prefix="/reports", tags=["reports"])

@router.get("/ping", tags=["reports"])
async def reports_ping():
    return {"ok": True, "scope": "reports"}

@router.get("/pdf/{campaign_id}", tags=["reports"])
async def get_report_file(campaign_id: str):
    """
    Opción B (por si guardaste PDFs en /tmp), devuelve un PDF por ID si existe.
    """
    file_path = f"/tmp/{campaign_id}.pdf"
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(file_path, media_type="application/pdf", filename=f"{campaign_id}.pdf")

@router.post("/pdf", tags=["reports"])
async def create_report_pdf(payload: Dict[str, Any]):
    """
    Espera JSON:
    {
      "campaign": { "name": "...", "query": "..." },
      "analysis": {
        "summary": "...",
        "sentiment_label": "...",
        "sentiment_score": 0.23,
        "sentiment_score_pct": 61,          # opcional
        "topics": ["..."],
        "items": [
           {
             "title": "...",
             "url": "https://...",
             "source": "...",
             "llm": {
               "summary": "...",
               "sentiment_label": "...",
               "sentiment_score": 0.1,
               "sentiment_score_pct": 55     # opcional
             }
           },
           ...
        ]
      }
    }
    """
    try:
        campaign = payload.get("campaign") or {}
        analysis = payload.get("analysis") or {}
        if not analysis:
            raise HTTPException(status_code=400, detail="analysis es requerido")

        # Genera el PDF en memoria (bytes)
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