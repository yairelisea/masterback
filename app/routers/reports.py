
# ==============================
# 2) Fallback a microservicio
# ==============================
async def _proxy_pdf_service(payload, suggested_name):
    pdf_service = (os.getenv("PDF_SERVICE_URL") or PDF_SERVICE_URL or "").rstrip("/")
    if not pdf_service:
        # Sin microservicio configurado
        raise HTTPException(status_code=500, detail="PDF_SERVICE_URL not configured")

    url = f"{pdf_service}/pdf"  # Ruta del microservicio

    try:
        # Usamos streaming para evitar transformaciones accidentales y garantizar bytes crudos
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            async with client.stream(
                "POST",
                url,
                json=payload,
                headers={"Accept": "application/pdf"},
            ) as resp:
                status = resp.status_code
                if status >= 300:
                    # Leemos cuerpo de error como texto para diagnóstico
                    err_text = await resp.aread()
                    raise HTTPException(status_code=status, detail=err_text.decode("utf-8", errors="replace"))

                # Acumulamos los bytes del PDF
                chunks = []
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        chunks.append(chunk)
                pdf_bytes = b"".join(chunks)

                # Validar cabecera PDF
                _assert_pdf_bytes(pdf_bytes)

                # Intentar filename desde Content-Disposition
                disp = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition") or ""
                filename_from_service = _extract_filename(disp)
                final_name = safe_filename(filename_from_service or suggested_name)

        # Devolver exactamente los bytes recibidos como PDF
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
        # Error de red/timeout/formato, etc.
        raise HTTPException(status_code=502, detail=f"PDF proxy failed: {e}")