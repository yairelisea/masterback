from __future__ import annotations
import os
import httpx

PDF_SERVICE_URL = os.getenv("PDF_SERVICE_URL", "").rstrip("/")

class PdfServiceError(Exception):
    pass

async def render_pdf_via_service(payload: dict) -> bytes:
    """
    Envía el payload (campaign + analysis) al microservicio y regresa bytes del PDF.
    Espera que el microservicio exponga POST /render (application/json) -> application/pdf
    """
    if not PDF_SERVICE_URL:
        raise PdfServiceError("PDF_SERVICE_URL no configurado")

    url = f"{PDF_SERVICE_URL}/render"
    timeout = httpx.Timeout(60.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code >= 400:
            # intenta leer json de error si existe
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise PdfServiceError(f"PDF service error {resp.status_code}: {detail}")
        return resp.content