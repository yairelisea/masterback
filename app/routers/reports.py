# app/routers/reports.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, FileResponse, Response
from typing import Any, Dict
import io, os

from app.services.report import generate_pdf_from_analysis

router = APIRouter(prefix="/reports", tags=["reports"])

@router.get("/ping", tags=["reports"])
async def reports_ping():
    return {"ok": True, "scope": "reports"}

@router.get("/pdf/{campaign_id}", tags=["reports"])
async def get_report(campaign_id: str):
    """
    Opción B (por si guardaste PDFs en /tmp), devuelve un PDF por ID si existe.
    """
    file_path = f"/tmp/{campaign_id}.pdf"
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(file_path, media_type="application/pdf", filename=f"{campaign_id}.pdf")

@router.post("/pdf", tags=["reports"])
async def post_report(payload: Dict[str, Any]):
    """
    Espera:
    {
      "campaign": {...},
      "analysis": {...}
    }
    No recalcula el análisis: sólo renderiza y responde el PDF.
    """
    try:
        campaign = payload.get("campaign") or {}
        analysis = payload.get("analysis") or {}
        if not analysis:
            raise HTTPException(status_code=400, detail="analysis es requerido")

        result = generate_pdf_from_analysis(campaign=campaign, analysis=analysis)

        # Si el servicio ya devolvió una Response (raro, pero por si acaso), la regresamos tal cual
        if isinstance(result, Response):
            return result

        pdf_bytes: bytes
        filename: str | None = None
        content_type: str = "application/pdf"

        if isinstance(result, (list, tuple)):
            # Aceptamos (bytes,), (bytes, filename), (bytes, filename, content_type)
            if not result:
                raise ValueError("La función de generación devolvió un tuple vacío.")
            pdf_bytes = result[0]
            if len(result) >= 2 and isinstance(result[1], str):
                filename = result[1]
            if len(result) >= 3 and isinstance(result[2], str):
                content_type = result[2]
        else:
            # Asumimos que es bytes
            pdf_bytes = result  # type: ignore[assignment]

        if not isinstance(pdf_bytes, (bytes, bytearray)):
            raise TypeError("a bytes-like object is required, not %r" % type(pdf_bytes).__name__)

        # Nombre por defecto si no llegó
        if not filename:
            filename = (campaign.get("name") or campaign.get("query") or "Reporte") + ".pdf"

        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")