# app/routers/reports.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse
from typing import Any, Dict, Optional
from app.services.report import generate_report_pdf
import io
import os

router = APIRouter(tags=["reports"])

@router.get("/pdf/{campaign_id}")
async def get_report(campaign_id: str):
    """
    Serves a PDF report file from /tmp/{campaign_id}.pdf if it exists.
    """
    file_path = f"/tmp/{campaign_id}.pdf"
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(file_path, media_type="application/pdf", filename=f"{campaign_id}.pdf")

@router.post("/pdf")
async def post_report(payload: Dict[str, Any]):
    """
    Expects JSON with parameters:
    {
      "q": "...",
      "size": "...",
      "days_back": ...,
      "lang": "...",
      "country": "..."
    }
    Generates a PDF report using generate_report_pdf.
    """
    try:
        q = payload.get("q")
        size = payload.get("size", "A4")
        days_back = payload.get("days_back", 7)
        lang = payload.get("lang", "en")
        country = payload.get("country", "US")

        pdf = await generate_report_pdf(q=q, size=size, days_back=days_back, lang=lang, country=country)

        filename = "Report.pdf"
        return StreamingResponse(
            io.BytesIO(pdf),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")