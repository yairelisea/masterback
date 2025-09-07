# app/routers/reports.py
from __future__ import annotations

import io
import os
import re
from typing import Any, Dict, Optional, Tuple, Union

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse, Response
import httpx

# Intentamos usar el servicio interno si existe
try:
    # Debe devolver bytes o (bytes, filename)
    from app.services.report import generate_best_effort_report  # type: ignore
except Exception:
    generate_best_effort_report = None  # fallback a microservicio externo

router = APIRouter(prefix="/reports", tags=["reports"])

# URL del microservicio externo de PDF (usado en el fallback inferior).
PDF_SERVICE_URL = os.getenv("PDF_SERVICE_URL", "").rstrip("/")

# --------------------------------------------------------------------
# GET /reports/pdf/{campaign_id}  (sirve un pdf ya generado en /tmp)
# --------------------------------------------------------------------
@router.get("/pdf/{campaign_id}")
async def get_report(campaign_id: str):
    file_path = f"/tmp/{campaign_id}.pdf"
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=safe_filename(campaign_id),
    )

# --------------------------------------------------------------------
# POST /reports/pdf
#   Espera JSON con al menos: { campaign: {...}, analysis: {...} }
#   Genera PDF y lo regresa como attachment
# --------------------------------------------------------------------
@router.post("/pdf")
async def post_report(payload: Dict[str, Any], request: Request):
    """
    Payload esperado desde el front:
    {
      "campaign": { "name": "...", "query": "...", ... },
      "analysis": {
        "summary": "...",
        "sentiment_label": "...",
        "sentiment_score": 0.23,
        "sentiment_score_pct": 61,   # opcional
        "topics": [...],
        "items": [
          { "title": "...", "url": "...", "source": "...",
            "llm": { "summary": "...", "sentiment_label": "...", "sentiment_score": 0.12, "sentiment_score_pct": 56 } },
          ...
        ]
      }
    }
    No recalcula IA: solo renderiza y devuelve el PDF.
    """
    # Validación mínima
    campaign = payload.get("campaign") or {}
    analysis = payload.get("analysis") or {}
    if not analysis:
        raise HTTPException(status_code=400, detail="analysis es requerido")

    # Nombre sugerido del archivo
    suggested_name = (campaign.get("name") or campaign.get("query") or "Reporte").strip() or "Reporte"

    # 1) Intento con servicio interno (si está disponible y operativo)
    if callable(generate_best_effort_report):
        try:
            # Puede ser sync o async y puede devolver bytes o (bytes, filename)
            result = await _maybe_async(
                generate_best_effort_report,
                campaign=campaign,
                analysis=analysis,
            )

            default_name = safe_filename(suggested_name)
            pdf_bytes, final_name = _normalize_pdf_result(result, default_name)
            _assert_pdf_bytes(pdf_bytes)

            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="{final_name}"',
                    "Access-Control-Expose-Headers": "Content-Disposition",
                },
            )
        except HTTPException:
            raise
        except Exception:
            # si falla, continuamos con el fallback externo
            pass

    # 2) Fallback a microservicio externo (recomendado para Render/Netlify)
    pdf_service = PDF_SERVICE_URL
    if not pdf_service:
        raise HTTPException(status_code=500, detail="PDF_SERVICE_URL not configured")

    try:
        url = f"{pdf_service}/pdf"  # ruta correcta del microservicio
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Accept": "application/pdf"},  # pedimos PDF explícitamente
            )

        if resp.status_code >= 300:
            # Propaga texto de error del microservicio
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        # SIEMPRE trabajar con bytes, NO con .text
        pdf_bytes = resp.content or b""
        _assert_pdf_bytes(pdf_bytes, resp)

        # Intentar extraer filename del microservicio si lo envió
        disp = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition") or ""
        filename_from_service = _extract_filename(disp)

        # Nombre final
        final_name = safe_filename(filename_from_service or suggested_name)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{final_name}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"PDF proxy failed: {e}")

# ---------------------
# Utilidades
# ---------------------
def safe_filename(name: Optional[str]) -> str:
    """
    Convierte un texto en un nombre de archivo seguro para cabeceras HTTP.
    Reemplaza espacios por guiones bajos y elimina caracteres problemáticos.
    """
    base = (name or "Reporte").strip()
    base = base.replace(" ", "_")  # espacios -> underscore (evita problemas en descargas)
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    base = "".join(ch for ch in base if ch in allowed)
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base

def _extract_filename(content_disposition: str) -> Optional[str]:
    """
    Extrae filename de Content-Disposition si existe.
    Acepta variantes con filename* y comillas.
    """
    if not content_disposition:
        return None
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition, flags=re.IGNORECASE)
    return m.group(1) if m else None

def _assert_pdf_bytes(pdf_bytes: Union[bytes, bytearray], resp: httpx.Response | None = None) -> None:
    """
    Verifica que los bytes empiecen con '%PDF-'. Si no, intenta producir
    un detalle legible para diagnóstico.
    """
    if not isinstance(pdf_bytes, (bytes, bytearray)) or not pdf_bytes:
        raise HTTPException(status_code=500, detail="Empty or invalid PDF bytes")
    if not bytes(pdf_bytes).startswith(b"%PDF-"):
        preview = ""
        if resp is not None:
            try:
                preview = resp.text[:280]
            except Exception:
                preview = ""
        raise HTTPException(status_code=500, detail=f"PDF service returned non-PDF: {preview or 'invalid header'}")

def _normalize_pdf_result(
    result: Union[bytes, bytearray, Tuple[Union[bytes, bytearray], Optional[str]]],
    fallback_name: str,
) -> Tuple[bytes, str]:
    """
    Acepta:
      - bytes
      - (bytes, "filename.pdf")
    y normaliza a (bytes, filename).
    """
    if isinstance(result, (bytes, bytearray)):
        return bytes(result), fallback_name

    if isinstance(result, tuple) and len(result) >= 1:
        data = result[0]
        name = result[1] if len(result) >= 2 else None
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("PDF generator must return bytes or (bytes, filename)")
        final_name = safe_filename(name or fallback_name)
        return bytes(data), final_name

    raise TypeError("PDF generator must return bytes or (bytes, filename)")

async def _maybe_async(fn, *args, **kwargs):
    """Permite llamar funciones sync o async con la misma interfaz."""
    res = fn(*args, **kwargs)
    if hasattr(res, "__await__"):
        return await res
    return res