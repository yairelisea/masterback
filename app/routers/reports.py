# app/routers/reports.py
from __future__ import annotations

import io
import os
from typing import Any, Dict, Optional, Tuple, Union

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, FileResponse
import httpx

# Intentamos usar el servicio interno si existe
try:
    # Debe devolver bytes o (bytes, filename)
    from app.services.report import generate_best_effort_report  # type: ignore
except Exception:
    generate_best_effort_report = None  # fallback a microservicio externo

router = APIRouter(prefix="/reports", tags=["reports"])

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
        filename=f"{campaign_id}.pdf",
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
    suggested_name = (campaign.get("name") or campaign.get("query") or "Reporte").strip()
    if not suggested_name:
        suggested_name = "Reporte"
    filename = f"{suggested_name}.pdf"

    # 1) Intento con servicio interno (si está disponible y operativo)
    if callable(generate_best_effort_report):
        try:
            # Genera el PDF en memoria (bytes)
            # Si tu generador se llama distinto, cámbialo aquí:
            pdf_bytes = generate_best_effort_report(campaign=campaign, analysis=analysis)

            filename = safe_filename(campaign.get("name") or campaign.get("query") or "Reporte")

            return StreamingResponse(
                io.BytesIO(pdf_bytes),
                media_type="application/pdf",
                headers={
                    # Dispara descarga directa
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    # Permite al frontend leer Content-Disposition vía CORS
                    "Access-Control-Expose-Headers": "Content-Disposition",
                },
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    # 2) Fallback a microservicio externo (recomendado para Render/Netlify)
    pdf_service = os.getenv("PDF_SERVICE_URL", "").rstrip("/")
    if not pdf_service:
        # No hay weasyprint/playwright interno ni microservicio configurado
        raise HTTPException(status_code=500, detail="WEASYPRINT_MISSING")

    # Probamos /render y luego /pdf
    for path in ("/render", "/pdf"):
        try:
            url = f"{pdf_service}{path}"
            async with httpx.AsyncClient(timeout=60) as client:
                # Envía tal cual el payload del front
                resp = await client.post(url, json=payload)
            if resp.status_code == 404:
                # intenta siguiente path
                continue
            if resp.status_code >= 300:
                # devolvemos el error del microservicio
                raise HTTPException(status_code=resp.status_code, detail=resp.text)

            pdf_bytes = resp.content
            if not isinstance(pdf_bytes, (bytes, bytearray)) or len(pdf_bytes) == 0:
                raise HTTPException(status_code=500, detail="Servicio PDF devolvió respuesta vacía")

            return StreamingResponse(
                io.BytesIO(pdf_bytes),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        except HTTPException:
            raise
        except Exception as e:
            # intenta el siguiente path o al final cae en error genérico
            last_error = str(e)
            continue

    try:
        timeout = httpx.Timeout(60.0, connect=20.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            # IMPORTANTE: usamos stream para no cargar todo en memoria si no quieres
            resp = await client.post(PDF_SERVICE_URL, json=payload)
            # Si hay error, intenta devolver el cuerpo de error legible
            if resp.status_code >= 400:
                # Intenta texto para ver el mensaje del microservicio
                err_txt = None
                try:
                    err_txt = resp.text
                except Exception:
                    err_txt = f"status={resp.status_code}"
                raise HTTPException(status_code=500, detail=f"PDF service error: {err_txt}")

            # Verifica content-type del microservicio
            ctype = resp.headers.get("content-type", "")
            if "application/pdf" not in ctype.lower():
                # Algo fue mal: probablemente devolvió HTML/JSON de error
                err_preview = (resp.text[:300] if hasattr(resp, "text") else "unknown")
                raise HTTPException(status_code=500, detail=f"PDF service returned non-PDF: {err_preview}")

            # Opción A: leer bytes y responder
            pdf_bytes = resp.content  # <- bytes reales del PDF
            filename = "reporte.pdf"
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            )

            # Opción B (streaming):
            # return StreamingResponse(
            #     resp.aiter_bytes(),
            #     media_type="application/pdf",
            #     headers={"Content-Disposition": f'attachment; filename="{filename}"'}
            # )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    raise HTTPException(status_code=502, detail="No fue posible generar el PDF (servicio externo no disponible).")


# ---------------------
# Utilidades internas
# ---------------------
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
        final_name = name or fallback_name
        return bytes(data), final_name

    raise TypeError("PDF generator must return bytes or (bytes, filename)")


async def _maybe_async(fn, *args, **kwargs):
    """Permite llamar funciones sync o async con la misma interfaz."""
    res = fn(*args, **kwargs)
    if hasattr(res, "__await__"):
        return await res
    return res