# app/routers/reports.py
from __future__ import annotations
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import Any, Dict
from ..services.report import build_report_html
from playwright.async_api import async_playwright
import io

router = APIRouter(prefix="/reports", tags=["reports"])

async def html_to_pdf_bytes(html: str) -> bytes:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html, wait_until="load")
        pdf_bytes = await page.pdf(format="A4", margin={"top":"16mm","right":"14mm","bottom":"16mm","left":"14mm"})
        await browser.close()
        return pdf_bytes

@router.post("/render-pdf")
async def render_pdf(payload: Dict[str, Any]):
    """
    Espera JSON:
    {
      "html": "..."
    }
    Genera un PDF en backend a partir del HTML proporcionado y lo devuelve como archivo.
    """
    try:
        html = payload.get("html") or ""
        pdf = await html_to_pdf_bytes(html)

        filename = "Reporte.pdf"
        return StreamingResponse(
            io.BytesIO(pdf),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")