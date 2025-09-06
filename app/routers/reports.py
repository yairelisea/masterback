# app/routers/reports.py
from __future__ import annotations
from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse
from io import BytesIO
from typing import Any, Dict, List, Optional
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

router = APIRouter(prefix="/reports", tags=["reports"])

def _pct(score: Optional[float]) -> str:
    if score is None:
        return "N/A"
    # ya normalizamos a [0,100] en el front; por si llegara 0..1:
    return f"{(score*100 if score <= 1 else score):.0f}%"

@router.post("/analysis", response_class=StreamingResponse)
async def analysis_report(
    payload: Dict[str, Any] = Body(..., description="Debe contener {campaign, analysis}")
):
    """
    Espera:
    {
      "campaign": { "name": "...", "query": "...", ... },
      "analysis": {
        "summary": "...",
        "sentiment_label": "...",
        "sentiment_score": 0-100 (o 0..1),
        "topics": ["...","..."],
        "items": [
          { "title":"...", "url":"...", "summary":"...", "source":"...", "pubDate":"..." },
          ...
        ]
      }
    }
    Devuelve un PDF con ese contenido (no re-ejecuta IA).
    """
    campaign = payload.get("campaign") or {}
    analysis = payload.get("analysis") or {}
    items: List[Dict[str, Any]] = analysis.get("items") or []

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=40, rightMargin=40, topMargin=50, bottomMargin=40)

    styles = getSampleStyleSheet()
    H1 = styles["Heading1"]
    H2 = styles["Heading2"]
    P  = styles["BodyText"]

    # Estilos personalizados
    Title = ParagraphStyle(
        "Title",
        parent=H1,
        textColor=colors.HexColor("#111827"),
        fontSize=18,
        spaceAfter=12
    )
    Sub = ParagraphStyle(
        "Sub",
        parent=P,
        textColor=colors.HexColor("#6B7280"),
        fontSize=10,
        spaceAfter=6
    )
    Chip = ParagraphStyle(
        "Chip",
        parent=P,
        textColor=colors.white,
        backColor=colors.HexColor("#10B981"),  # verde
        fontSize=8,
        leftIndent=0,
        rightIndent=0,
        spaceBefore=3,
        spaceAfter=3,
        leading=10
    )
    Bold = ParagraphStyle(
        "Bold",
        parent=P,
        fontSize=10,
        textColor=colors.HexColor("#111827"),
        spaceAfter=4
    )
    Small = ParagraphStyle(
        "Small",
        parent=P,
        fontSize=9,
        textColor=colors.HexColor("#374151"),
    )

    story: List[Any] = []

    # Encabezado
    story.append(Paragraph("Reporte de Análisis IA", Title))
    meta_line = f"Campaña: <b>{campaign.get('name', 'N/A')}</b> — Consulta: <b>{campaign.get('query','N/A')}</b>"
    story.append(Paragraph(meta_line, Sub))
    story.append(Spacer(1, 8))

    # Resumen + Sentimiento
    sentiment_pct = _pct(analysis.get("sentiment_score"))
    sent_label = analysis.get("sentiment_label") or "N/A"
    sum_text = analysis.get("summary") or "Sin resumen."

    story.append(Paragraph("Resumen", H2))
    story.append(Paragraph(sum_text, P))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"Sentimiento: <b>{sent_label}</b> — Score: <b>{sentiment_pct}</b>", Bold))
    story.append(Spacer(1, 10))

    # Tópicos como chips verdes
    topics = analysis.get("topics") or []
    if topics:
        story.append(Paragraph("Temas", H2))
        # Hacemos una fila de chips usando Table
        chips = [[Paragraph(t, Chip) for t in topics]]
        tbl = Table(chips, style=TableStyle([
            ("LEFTPADDING", (0,0), (-1,-1), 4),
            ("RIGHTPADDING", (0,0), (-1,-1), 4),
            ("TOPPADDING", (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 12))

    # Lista de artículos
    story.append(Paragraph("Artículos Analizados", H2))

    # Tabla con: Título (link), Fuente/Fecha, Resumen
    data = [["Título", "Fuente / Fecha", "Resumen"]]
    for it in items[:50]:
        title = it.get("title") or "Sin título"
        url = it.get("url")
        source = it.get("source") or ""
        pub = it.get("pubDate") or ""
        sm = it.get("summary") or it.get("llm", {}).get("summary") or ""

        # Título con link
        if url:
            title_par = Paragraph(f'<link href="{url}">{title}</link>', P)
        else:
            title_par = Paragraph(title, P)

        meta_par = Paragraph(f"{source}<br/>{pub}", Small)
        sum_par  = Paragraph(sm, Small)

        data.append([title_par, meta_par, sum_par])

    table = Table(data, colWidths=[240, 120, 180], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#F3F4F6")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#111827")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,0), 10),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#FAFAFA")]),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(table)

    doc.build(story)

    buf.seek(0)
    filename = f"reporte_{(campaign.get('name') or 'campana').replace(' ','_')}.pdf"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"'
    }
    return StreamingResponse(buf, media_type="application/pdf", headers=headers)