# app/services/report.py
from __future__ import annotations
from typing import Optional
import io
from datetime import datetime

# ReportLab para generar PDF sin dependencias del sistema
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm

def _page_size_from_str(size: str):
    s = (size or "A4").upper().strip()
    return LETTER if s in ("LETTER", "LETRA", "CARTA", "US-LETTER") else A4

async def generate_report_pdf(
    q: str,
    size: str = "A4",
    days_back: int = 14,
    lang: str = "es-419",
    country: str = "MX",
) -> bytes:
    """
    Genera un PDF simple (en memoria) con ReportLab.
    No depende de Playwright/WeasyPrint. Funciona en Render.
    """
    if not q:
        q = "Consulta sin título"

    buffer = io.BytesIO()
    page_size = _page_size_from_str(size)
    c = canvas.Canvas(buffer, pagesize=page_size)

    width, height = page_size

    # Header
    c.setFont("Helvetica-Bold", 16)
    c.drawString(2*cm, height - 2*cm, "BLACKBOX MONITOR — Reporte de Cobertura")
    c.setFont("Helvetica", 10)
    c.drawString(2*cm, height - 2.7*cm, datetime.utcnow().strftime("Generado: %Y-%m-%d %H:%M UTC"))

    # Parámetros
    c.setFont("Helvetica", 11)
    y = height - 4*cm
    c.drawString(2*cm, y, f"Tema / Actor: {q}")
    y -= 0.7*cm
    c.drawString(2*cm, y, f"Días analizados: {days_back}")
    y -= 0.7*cm
    c.drawString(2*cm, y, f"Idioma: {lang}  ·  País: {country}")

    # Nota
    y -= 1.2*cm
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(2*cm, y, "Este PDF es una versión básica. Integraremos los resultados de IA y enlaces pronto.")
    y -= 0.7*cm
    c.drawString(2*cm, y, "Si ves este archivo, la ruta POST /reports/pdf ya está funcionando correctamente.")

    c.showPage()
    c.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes