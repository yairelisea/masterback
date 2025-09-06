# app/routers/reports.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Any, Dict, Optional
from app.services.report import generate_report_pdf
import io

router = APIRouter(prefix="/ai", tags=["ai"])

@router.get("/report")
async def get_report(
    q: Optional[str] = Query(None, description="Query string for report"),
    size: Optional[str] = Query("A4", description="Paper size for PDF"),
    days_back: Optional[int] = Query(7, description="Number of days back for data"),
    lang: Optional[str] = Query("en", description="Language code"),
    country: Optional[str] = Query("US", description="Country code"),
):
    """
    Generates a PDF report based on query parameters using generate_report_pdf.
    """
    try:
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

@router.post("/report")
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