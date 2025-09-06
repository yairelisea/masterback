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
      <div class="small">Score: {{ sentiment_pct }}%</div>
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
          {% if it.source %}<div class="small">{{ it.source }}</div>{% endif %}
          {% if it.url %}<div class="small"><a href="{{ it.url }}">{{ it.url }}</a></div>{% endif %}
          {% if it.summary %}<div class="small" style="margin-top:4px">{{ it.summary }}</div>{% endif %}
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
    name = campaign.get("name") or "Campaña"
    q = campaign.get("query") or ""
    summary = analysis.get("summary")
    sentiment_label = analysis.get("sentiment_label")
    sentiment_score = analysis.get("sentiment_score")
    sentiment_pct = None
    if isinstance(sentiment_score, (int, float)):
        sentiment_pct = round(max(0, min(1, sentiment_score)) * 100)

    topics: List[str] = analysis.get("topics") or []
    items = analysis.get("items") or []

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