from __future__ import annotations

import io
import os
import re
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

# Router mounted in app.main as: app.include_router(reports.router)
router = APIRouter(prefix="/reports", tags=["reports"])

# You can override via environment variable in Render
PDF_SERVICE_URL = os.getenv("PDF_SERVICE_URL", "").rstrip("/")


def _extract_filename(content_disposition: str) -> Optional[str]:
    """
    Parse filename from a Content-Disposition header if present.
    Supports: filename="...", filename=..., and RFC5987 filename*=
    """
    if not content_disposition:
        return None

    # RFC 5987 style: filename*=UTF-8''some%20name.pdf
    m = re.search(r"filename\*\s*=\s*([^']*)'[^']*'([^;]+)", content_disposition, flags=re.IGNORECASE)
    if m:
        try:
            import urllib.parse as _up
            return _up.unquote(m.group(2))
        except Exception:
            pass

    # Simple filename="..."
    m = re.search(r'filename\s*=\s*"([^"]+)"', content_disposition, flags=re.IGNORECASE)
    if m:
        return m.group(1)

    # Simple filename=...
    m = re.search(r"filename\s*=\s*([^;]+)", content_disposition, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return None


def safe_filename(name: Optional[str]) -> str:
    """
    Convert a text to a safe filename for HTTP Content-Disposition.
    """
    base = (name or "Reporte").strip()
    base = base.replace(" ", "_")
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    base = "".join(ch for ch in base if ch in allowed)
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base


def _assert_pdf_bytes(b: bytes) -> None:
    """
    Raise if the buffer does not look like a PDF (magic: %PDF).
    """
    if not isinstance(b, (bytes, bytearray)) or len(b) < 5 or not bytes(b).startswith(b"%PDF"):
        # Helpful preview for debugging (first bytes as hex)
        preview = bytes(b[:10]).hex() if isinstance(b, (bytes, bytearray)) else "<non-bytes>"
        raise HTTPException(status_code=502, detail=f"Upstream response is not PDF (first bytes: {preview})")


async def _proxy_pdf_service(payload: Dict[str, Any], suggested_name: str) -> StreamingResponse:
    """
    Call the external PDF microservice and stream raw PDF bytes back to the client.
    """
    pdf_service = (os.getenv("PDF_SERVICE_URL") or PDF_SERVICE_URL or "").rstrip("/")
    if not pdf_service:
        raise HTTPException(status_code=500, detail="PDF_SERVICE_URL not configured")

    url = f"{pdf_service}/pdf"  # microservice route

    try:
        # Use streaming to avoid any transformations; ensure raw bytes.
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            async with client.stream(
                "POST",
                url,
                json=payload,
                headers={"Accept": "application/pdf"},
            ) as resp:
                if resp.status_code >= 300:
                    # Read error payload as text for diagnostics
                    err_text = await resp.aread()
                    raise HTTPException(
                        status_code=resp.status_code,
                        detail=err_text.decode("utf-8", errors="replace"),
                    )

                # Accumulate the PDF bytes
                chunks = []
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        chunks.append(chunk)
                pdf_bytes = b"".join(chunks)

                # Validate magic header
                _assert_pdf_bytes(pdf_bytes)

                # Try to get filename from Content-Disposition
                disp = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition") or ""
                filename_from_service = _extract_filename(disp)
                final_name = safe_filename(filename_from_service or suggested_name)

        # Send exactly the bytes we received
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{final_name}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
                "Cache-Control": "no-store",
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        # Network/timeout/format error, etc.
        raise HTTPException(status_code=502, detail=f"PDF proxy failed: {e}")


@router.post("/pdf")
async def post_report(payload: Dict[str, Any], request: Request):
    """
    Accepts JSON payload from the front-end and returns a generated PDF.
    This endpoint does not recalculate analysis; it only renders via the PDF microservice.
    Expected minimal payload:
    {
      "campaign": {"name": "...", "query": "..."},
      "analysis": {...}
    }
    """
    campaign = payload.get("campaign") or {}
    analysis = payload.get("analysis") or {}
    if not analysis:
        raise HTTPException(status_code=400, detail="analysis es requerido")

    suggested_name = (campaign.get("name") or campaign.get("query") or "Reporte").strip() or "Reporte"
    return await _proxy_pdf_service(payload, suggested_name)