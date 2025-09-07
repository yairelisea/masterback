# app/routers/reports.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from typing import Any, Dict
import io, os

from app.services.report import generate_pdf_from_analysis

router = APIRouter(prefix="/reports", tags=["reports"])

@router.get("/pdf/{campaign_id}")
async def get_report(campaign_id: str):
    file_path = f"/tmp/{campaign_id}.pdf"
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(file_path, media_type="application/pdf", filename=f"{campaign_id}.pdf")

@router.post("/pdf")
async def post_report(payload: Dict[str, Any]):
    """
    Espera:
    {
      "campaign": { "name": "...", "query": "...", ... },
      "analysis": {
        "summary": "...",
        "sentiment_label": "...",
        "sentiment_score": 0.23,
        "sentiment_score_pct": 61,   # opcional
        "topics": [...],
        "items": [ { title, url, source, llm:{summary, sentiment_label, sentiment_score(_pct)} }, ... ]
      }
    }
    NO re-calcula el análisis. Solo renderiza y envía el PDF.
    """
    try:
        campaign = payload.get("campaign") or {}
        analysis = payload.get("analysis") or {}
        if not analysis:
            raise HTTPException(status_code=400, detail="analysis es requerido")

        pdf = generate_pdf_from_analysis(campaign=campaign, analysis=analysis)
        filename = (campaign.get("name") or campaign.get("query") or "Reporte") + ".pdf"

        return StreamingResponse(
            io.BytesIO(pdf),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")