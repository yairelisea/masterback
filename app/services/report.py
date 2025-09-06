# app/services/report.py
from __future__ import annotations
from typing import Dict, Any, List
from jinja2 import Environment, BaseLoader

HTML_TMPL = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{{ title }}</title>
  <style>
    body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; color:#111827; margin:16px; }
    h1 { margin:0 0 4px }
    .muted { color:#6b7280; font-size:12px; }
    .grid { display:flex; gap:12px; margin-top:12px; }
    .card { border:1px solid #e5e7eb; border-radius:12px; padding:12px 16px; margin:10px 0; }
    .pill { display:inline-block; font-size:12px; padding:4px 8px; border-radius:9999px; background:#e5f7ed; color:#065f46; margin:2px 6px 2px 0; }
    a { color:#1d4ed8; text-decoration: underline; word-break: break-all; }
    .small { font-size:13px; color:#374151; }
    .row { display:flex; gap:12px; }
    .col { flex:1; }
    .section-title { font-size:14px; color:#6b7280; margin-bottom:6px; }
    .item { border:1px solid #e5e7eb; border-radius:10px; padding:10px 12px; margin:8px 0; }
    .item-meta { color:#6b7280; font-size:12px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:6px 0; }
    .tag { display:inline-block; padding:2px 6px; border-radius: 6px; background:#f1f5f9; color:#334155; border:1px solid #e2e8f0; }
    .tag.pct { background:#ecfeff; color:#075985; border-color:#bae6fd; }
  </style>
</head>
<body>
  <h1>{{ header }}</h1>
  <div class="muted">{{ subheader }}</div>

  <div class="grid">
    <div class="card col">
      <div class="section-title">Sentimiento</div>
      <div><strong>{{ sentiment_label or 'N/A' }}</strong></div>
      {% if sentiment_pct is not none %}
      <div class="small">Sentimiento: {{ sentiment_pct }}%</div>
      {% endif %}
    </div>
    <div class="card col">
      <div class="section-title">Resumen</div>
      <div class="small">{{ summary or 'Sin resumen.' }}</div>
    </div>
  </div>

  {% if topics and topics|length > 0 %}
  <div class="card">
    <div class="section-title">Temas</div>
    {% for t in topics %}
      <span class="pill">{{ t }}</span>
    {% endfor %}
  </div>
  {% endif %}

  <div class="card">
    <div class="section-title">Artículos analizados</div>
    {% if items and items|length > 0 %}
      {% for it in items %}
        <div class="item">
          <div><strong>{{ it.title or ('Nota ' ~ loop.index) }}</strong></div>
          <div class="item-meta">
            {% if it.llm_label %}<span class="tag">{{ it.llm_label }}</span>{% endif %}
            {% if it.llm_pct is not none %}<span class="tag pct">{{ it.llm_pct }}%</span>{% endif %}
            {% if it.source %}<span>{{ it.source }}</span>{% endif %}
            {% if it.url %}<a href="{{ it.url }}">{{ it.url }}</a>{% endif %}
          </div>
          {% if it.summary %}<div class="small">{{ it.summary }}</div>{% endif %}
        </div>
      {% endfor %}
    {% else %}
      <div class="small">No se encontraron artículos.</div>
    {% endif %}
  </div>
</body>
</html>
"""

env = Environment(loader=BaseLoader(), autoescape=True)

def build_report_html(campaign: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    name = (campaign or {}).get("name") or "Campaña"
    q = (campaign or {}).get("query") or ""

    summary = (analysis or {}).get("summary")
    sentiment_label = (analysis or {}).get("sentiment_label")

    # Overall %: prefer explicit percent, else map score (-1..1) -> 0..100
    sentiment_pct = None
    if isinstance((analysis or {}).get("sentiment_score_pct"), (int, float)):
        sentiment_pct = round((analysis or {}).get("sentiment_score_pct"))
    else:
        s = (analysis or {}).get("sentiment_score")
        if isinstance(s, (int, float)):
            try:
                s = max(-1.0, min(1.0, float(s)))
                sentiment_pct = round(((s + 1.0) / 2.0) * 100.0)
            except Exception:
                sentiment_pct = None

    topics: List[str] = (analysis or {}).get("topics") or []

    # Normalize items with LLM details
    items_raw = (analysis or {}).get("items") or []
    items: List[Dict[str, Any]] = []
    for it in items_raw:
        it = it or {}
        llm = it.get("llm") or {}
        # label and percent
        llm_label = llm.get("sentiment_label")
        if isinstance(llm.get("sentiment_score_pct"), (int, float)):
            llm_pct = round(llm.get("sentiment_score_pct"))
        else:
            ls = llm.get("sentiment_score")
            if isinstance(ls, (int, float)):
                try:
                    ls = max(-1.0, min(1.0, float(ls)))
                    llm_pct = round(((ls + 1.0) / 2.0) * 100.0)
                except Exception:
                    llm_pct = None
            else:
                llm_pct = None

        items.append({
            "title": it.get("title") or it.get("headline"),
            "source": it.get("source"),
            "url": it.get("url") or it.get("link"),
            "summary": llm.get("summary") or it.get("summary"),
            "llm_label": llm_label,
            "llm_pct": llm_pct,
        })

    tmpl = env.from_string(HTML_TMPL)
    return tmpl.render(
        title=f"Reporte - {name}",
        header=f"Reporte de Análisis – {name}",
        subheader=f"Consulta: {q}",
        summary=summary,
        sentiment_label=sentiment_label,
        sentiment_pct=sentiment_pct,
        topics=topics,
        items=items,
    )
def build_report_pdf(campaign: Dict[str, Any], analysis: Dict[str, Any]) -> bytes:
    """
    Build a PDF report using reportlab, similar to build_report_html.
    Returns the PDF as bytes.
    """
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors

    name = (campaign or {}).get("name") or "Campaña"
    q = (campaign or {}).get("query") or ""
    summary = (analysis or {}).get("summary")
    sentiment_label = (analysis or {}).get("sentiment_label")

    # Overall %: prefer explicit percent, else map score (-1..1) -> 0..100
    sentiment_pct = None
    if isinstance((analysis or {}).get("sentiment_score_pct"), (int, float)):
        sentiment_pct = round((analysis or {}).get("sentiment_score_pct"))
    else:
        s = (analysis or {}).get("sentiment_score")
        if isinstance(s, (int, float)):
            try:
                s = max(-1.0, min(1.0, float(s)))
                sentiment_pct = round(((s + 1.0) / 2.0) * 100.0)
            except Exception:
                sentiment_pct = None

    topics: List[str] = (analysis or {}).get("topics") or []
    items_raw = (analysis or {}).get("items") or []
    items: List[Dict[str, Any]] = []
    for it in items_raw:
        it = it or {}
        llm = it.get("llm") or {}
        llm_label = llm.get("sentiment_label")
        if isinstance(llm.get("sentiment_score_pct"), (int, float)):
            llm_pct = round(llm.get("sentiment_score_pct"))
        else:
            ls = llm.get("sentiment_score")
            if isinstance(ls, (int, float)):
                try:
                    ls = max(-1.0, min(1.0, float(ls)))
                    llm_pct = round(((ls + 1.0) / 2.0) * 100.0)
                except Exception:
                    llm_pct = None
            else:
                llm_pct = None
        items.append({
            "title": it.get("title") or it.get("headline"),
            "source": it.get("source"),
            "url": it.get("url") or it.get("link"),
            "summary": llm.get("summary") or it.get("summary"),
            "llm_label": llm_label,
            "llm_pct": llm_pct,
        })

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Title
    story.append(Paragraph(f"Reporte de Análisis – {name}", styles['Title']))
    story.append(Spacer(1, 6))
    # Subheader
    story.append(Paragraph(f"<font size=10 color='#888888'>Consulta: {q}</font>", styles['Normal']))
    story.append(Spacer(1, 14))

    # Sentiment and Summary as a table
    sentiment_str = sentiment_label or 'N/A'
    if sentiment_pct is not None:
        sentiment_str += f" ({sentiment_pct}%)"
    summary_str = summary or 'Sin resumen.'
    table_data = [
        [Paragraph("<b>Sentimiento</b>", styles['Normal']), Paragraph(sentiment_str, styles['Normal'])],
        [Paragraph("<b>Resumen</b>", styles['Normal']), Paragraph(summary_str, styles['Normal'])],
    ]
    t = Table(table_data, colWidths=[90, 400])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.whitesmoke),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.grey),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('TOPPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 14))

    # Topics
    if topics:
        story.append(Paragraph("<b>Temas:</b> " + ", ".join(topics), styles['Normal']))
        story.append(Spacer(1, 10))

    # Articles
    story.append(Paragraph("<b>Artículos analizados</b>", styles['Heading3']))
    story.append(Spacer(1, 4))
    if items:
        for idx, it in enumerate(items, 1):
            title = it.get("title") or f"Nota {idx}"
            meta = []
            if it.get("llm_label"):
                meta.append(str(it.get("llm_label")))
            if it.get("llm_pct") is not None:
                meta.append(f"{it.get('llm_pct')}%")
            if it.get("source"):
                meta.append(str(it.get("source")))
            if it.get("url"):
                meta.append(str(it.get("url")))
            meta_str = " | ".join(meta)
            story.append(Paragraph(f"<b>{title}</b>", styles['Normal']))
            if meta_str:
                story.append(Paragraph(f"<font size=9 color='#888'>{meta_str}</font>", styles['Normal']))
            if it.get("summary"):
                story.append(Paragraph(f"<font size=9>{it.get('summary')}</font>", styles['Normal']))
            story.append(Spacer(1, 8))
    else:
        story.append(Paragraph("<font size=9>No se encontraron artículos.</font>", styles['Normal']))

    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf


# Safe wrapper for PDF generation with filename suggestion
def generate_report_pdf(campaign: Dict[str, Any], analysis: Dict[str, Any]) -> tuple[bytes, str]:
    """
    Safe wrapper for build_report_pdf.
    Returns (pdf_bytes, filename).
    """
    try:
        pdf_bytes = build_report_pdf(campaign, analysis)
        name = (campaign or {}).get("name") or "campaña"
        filename = f"reporte_{name.replace(' ', '_')}.pdf"
        return pdf_bytes, filename
    except Exception as e:
        raise RuntimeError(f"Error al generar el PDF: {e}") from e