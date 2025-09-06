# app/routers/reports.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Any, Dict, Optional
from playwright.async_api import async_playwright
import io

router = APIRouter(prefix="/ai", tags=["ai"])

async def html_to_pdf_bytes(html: str) -> bytes:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html, wait_until="load")
        pdf_bytes = await page.pdf(format="A4", margin={"top":"16mm","right":"14mm","bottom":"16mm","left":"14mm"})
        await browser.close()
        return pdf_bytes

@router.get("/report")
async def get_report(
    q: Optional[str] = Query(None, description="Query string for report"),
    size: Optional[str] = Query("A4", description="Paper size for PDF"),
    # Additional query params can be added here as needed
):
    """
    Generates a simple PDF report based on query parameters.
    Currently returns a placeholder PDF until integrated with analysis data.
    """
    try:
        # Placeholder HTML content for the PDF
        html = f"<html><body><h1>Report</h1><p>Query: {q or 'N/A'}</p><p>Size: {size}</p></body></html>"
        pdf = await html_to_pdf_bytes(html)

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
    Expects JSON:
    {
      "html": "..."
    }
    Generates a PDF from the provided HTML and returns it as a file.
    """
    try:
        html = payload.get("html") or ""
        pdf = await html_to_pdf_bytes(html)

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