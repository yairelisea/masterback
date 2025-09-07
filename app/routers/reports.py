# app/services/report.py
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple
from jinja2 import Environment, BaseLoader
import datetime as dt

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _pct(score: Optional[float], pct: Optional[float]) -> Optional[int]:
    """Normaliza puntaje de sentimiento a 0..100.
    - Si ya viene porcentaje (0..100), lo redondea.
    - Si viene score -1..1, lo transforma a 0..100.
    """
    if isinstance(pct, (int, float)):
        try:
            return max(0, min(100, round(pct)))
        except Exception:
            return round(pct)  # best effort
    if isinstance(score, (int, float)):
        return max(0, min(100, round(((score + 1) / 2) * 100)))
    return None


HTML_TEMPLATE = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{{ title }}</title>
  <style>
    :root { --brand: #059669; --ink:#0f172a; --muted:#64748b; --border:#e5e7eb; --bg:#ffffff; }
    * { box-sizing: border-box }
    body { margin:0; padding:24px; font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Ubuntu,'Helvetica Neue',Arial,sans-serif; color:var(--ink); background:var(--bg); }
    .report { max-width: 900px; margin: 0 auto; }
    header { display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid var(--border); padding-bottom:12px; margin-bottom:16px; }
    .title { font-size:22px; font-weight:700; }
    .meta { color:var(--muted); font-size:12px; }
    .overall { display:grid; grid-template-columns: 1fr 2fr; gap:16px; border:1px solid var(--border); border-radius:10px; padding:16px; margin-bottom:16px; }
    .box { border:1px solid var(--border); border-radius:10px; padding:12px; }
    .box .label { font-size:11px; color:var(--muted); margin-bottom:4px; }
    .sentiment { font-weight:600; }
    .topics { display:flex; flex-wrap:wrap; gap:6px; }
    .topic { display:inline-block; padding:4px 8px; border-radius:999px; background:#d1fae5; color:#065f46; border:1px solid #a7f3d0; font-size:12px; }
    h2 { margin:16px 0 8px; font-size:18px; }
    .item { border:1px solid var(--border); border-radius:10px; padding:12px; margin-bottom:10px; }
    .item-title { font-weight:600; margin-bottom:6px; }
    .item-meta { color:var(--muted); font-size:12px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:6px; }
    .tag { display:inline-block; padding:2px 6px; border-radius:6px; background:#f1f5f9; color:#334155; border:1px solid #e2e8f0; }
    .tag.pct { background:#ecfeff; color:#075985; border-color:#bae6fd; }
    .source { opacity:.9; }
    .url { color: var(--brand); text-decoration: underline; }
    .foot { color:var(--muted); font-size:11px; text-align:center; margin-top:16px; }
    a { color: var(--brand); }
  </style>
</head>
<body>
  <div class="report">
    <header>
      <div class="title">{{ campaign_title }}</div>
      <div class="meta">{{ now }}</div>
    </header>

    <section class="overall">
      <div class="box">
        <div class="label">Sentimiento</div>
        <div class="sentiment">{{ overall_label or "N/A" }}</div>
        {% if overall_pct is not none %}
          <div class="meta">Sentimiento: {{ overall_pct }}%</div>
        {% endif %}
      </div>
      <div class="box">
        <div class="label">Resumen</div>
        <div>{{ overall_summary or "Sin resumen." }}</div>
      </div>
    </section>

    {% if topics and topics|length > 0 %}
    <section class="box" style="margin-bottom:16px">
      <div class="label">Temas relevantes</div>
      <div class="topics">
        {% for t in topics %}
          <span class="topic">{{ t }}</span>
        {% endfor %}
      </div>
    </section>
    {% endif %}

    <h2>Artículos analizados</h2>
    {% if items and items|length > 0 %}
      {% for it in items[:50] %}
        <div class="item">
          <div class="item-title">{{ it.title or it.headline or ("Nota " ~ loop.index) }}</div>
          <div class="item-meta">
            {% set it_label = it.llm.sentiment_label if it.llm else (it.sentiment_label if it.sentiment_label is defined else None) %}
            {% set it_pct = _pct(
                (it.llm.sentiment_score if it.llm else (it.sentiment_score if it.sentiment_score is defined else None)),
                (it.llm.sentiment_score_pct if it.llm else (it.sentiment_percent if it.sentiment_percent is defined else None))
            ) %}
            {% if it_label %}<span class="tag">{{ it_label }}</span>{% endif %}
            {% if it_pct is not none %}<span class="tag pct">{{ it_pct }}%</span>{% endif %}
            {% if it.source %}<span class="source">{{ it.source if it.source is string else (it.source.name if it.source.name is defined else "") }}</span>{% endif %}
            {% if it.url or it.link %}
              <a class="url" href="{{ it.url or it.link }}" target="_blank" rel="noreferrer">Abrir</a>
            {% endif %}
          </div>
          {% set short = (it.llm.summary if it.llm else None) or it.summary %}
          {% if short %}<div class="item-summary">{{ short }}</div>{% endif %}
        </div>
      {% endfor %}
    {% else %}
      <div class="meta">No se encontraron artículos.</div>
    {% endif %}

    <div class="foot">BLACKBOX MONITOR — Reporte generado automáticamente</div>
  </div>
</body>
</html>
"""

# -------------------------------------------------------------------
# Renderizado a HTML (siempre disponible)
# -------------------------------------------------------------------

def render_html_from_analysis(*, campaign: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    """Renderiza el HTML del reporte (sin convertir a PDF)."""
    env = Environment(loader=BaseLoader(), autoescape=True)
    tmpl = env.from_string(HTML_TEMPLATE)
    overall_pct = _pct(
        analysis.get("sentiment_score"), 
        analysis.get("sentiment_score_pct")
    )

    html = tmpl.render(
        title=f"{campaign.get('name') or campaign.get('query') or 'Campaña'} — Reporte",
        campaign_title=campaign.get("name") or campaign.get("query") or "Campaña",
        now=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        overall_label=analysis.get("sentiment_label"),
        overall_pct=overall_pct,
        overall_summary=analysis.get("summary"),
        topics=analysis.get("topics") or [],
        items=analysis.get("items") or [],
        _pct=_pct,  # helper para calcular % en items
    )
    return html

# -------------------------------------------------------------------
# PDF con WeasyPrint (lazy import y error claro si falta)
# -------------------------------------------------------------------

def generate_pdf_from_analysis(*, campaign: Dict[str, Any], analysis: Dict[str, Any]) -> bytes:
    """Convierte el HTML del reporte a PDF usando WeasyPrint.
    Lanza RuntimeError("WEASYPRINT_MISSING") si no está disponible.
    """
    try:
        from weasyprint import HTML  # lazy import para no romper en arranque
    except Exception as e:
        # Deja rastro claro para que el router haga fallback a HTML
        raise RuntimeError("WEASYPRINT_MISSING") from e

    html = render_html_from_analysis(campaign=campaign, analysis=analysis)
    pdf_bytes = HTML(string=html).write_pdf()
    return pdf_bytes

# -------------------------------------------------------------------
# Best-effort: intenta PDF y, si no, regresa HTML
# -------------------------------------------------------------------

def generate_best_effort_report(
    *, campaign: Dict[str, Any], analysis: Dict[str, Any]
) -> Tuple[bytes, str]:
    """Devuelve (data, mime_type):
       - Si hay WeasyPrint: (pdf_bytes, 'application/pdf')
       - Si NO hay WeasyPrint: (html_bytes, 'text/html; charset=utf-8')
    """
    try:
        pdf = generate_pdf_from_analysis(campaign=campaign, analysis=analysis)
        return pdf, "application/pdf"
    except RuntimeError as e:
        if str(e) == "WEASYPRINT_MISSING":
            html = render_html_from_analysis(campaign=campaign, analysis=analysis)
            return html.encode("utf-8"), "text/html; charset=utf-8"
        raise