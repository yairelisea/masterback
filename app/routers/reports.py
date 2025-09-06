from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Header, Request, Body
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from weasyprint import HTML
import tempfile
import datetime as dt
from typing import Any, Dict, List, Optional

from ..db import get_session
from ..models import Campaign, User
# Reutilizamos el mismo wrapper LLM que usa el router de IA
from ..services.llm import analyze_snippet
# Para evitar dependencia directa fuerte entre routers, copiamos un fetch mínimo
import urllib.parse
import httpx
import xml.etree.ElementTree as ET

router = APIRouter(prefix="/reports", tags=["reports"])

# ---------------------------
# Util: Google News RSS fetch (idéntico/compatible con ai_analysis)
# ---------------------------
async def fetch_google_news(
    q: str,
    size: int = 25,
    days_back: int = 14,
    lang: str = "es-419",
    country: str = "MX",
) -> List[Dict[str, Any]]:
    encoded_q = urllib.parse.quote_plus(q)
    base = "https://news.google.com/rss/search"
    params = f"?q={encoded_q}&hl={lang}&gl={country}&ceid={country}:{lang}"
    url = base + params

    items: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url)
        r.raise_for_status()
        xml = r.text

    root = ET.fromstring(xml)
    for item in root.findall("./channel/item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pubDate = item.findtext("pubDate") or ""
        source = ""
        source_tag = item.find("{http://search.yahoo.com/mrss/}source")
        if source_tag is None:
            s2 = item.find("source")
            if s2 is not None and s2.text:
                source = s2.text.strip()
        else:
            if source_tag.text:
                source = source_tag.text.strip()

        items.append({
            "title": title,
            "link": link,
            "pubDate": pubDate,
            "source": source,
        })

    if days_back and days_back > 0:
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=days_back)
        filtered: List[Dict[str, Any]] = []
        for it in items:
            try:
                parsed = dt.datetime.strptime(it["pubDate"], "%a, %d %b %Y %H:%M:%S %Z")
            except Exception:
                parsed = None
            if parsed is None or parsed >= cutoff:
                filtered.append(it)
        items = filtered

    return items[: max(1, min(size, 100))]


def score_to_pct(score: Optional[float]) -> Optional[int]:
    if score is None:
        return None
    try:
        v = float(score)
    except Exception:
        return None
    v = max(0.0, min(1.0, v))
    return int(round(v * 100))


def render_html_report(campaign: Campaign, overall: Dict[str, Any], items: List[Dict[str, Any]]) -> str:
    topics = overall.get("topics") or []
    sentiment_label = overall.get("sentiment_label")
    sentiment_score = score_to_pct(overall.get("sentiment_score"))
    summary = overall.get("summary") or "Sin resumen disponible."

    # CSS inline simple; WeasyPrint soporta mucho más si luego lo quieres separar
    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; color: #111827; }
    h1 { font-size: 22pt; margin: 0 0 8pt; }
    h2 { font-size: 16pt; margin: 16pt 0 6pt; }
    .muted { color: #6b7280; font-size: 10pt; }
    .pill { display:inline-block; background:#e6f7ed; color:#0e9f6e; border:1px solid #b7ebc6; border-radius:9999px; padding:2pt 6pt; margin:2pt 4pt 0 0; font-size:9pt; }
    .box { border:1px solid #e5e7eb; border-radius:8pt; padding:10pt; }
    .row { display:flex; gap:10pt; }
    .col { flex:1; }
    table { width:100%; border-collapse: collapse; }
    th, td { border:1px solid #e5e7eb; padding:6pt; font-size:9.5pt; vertical-align: top; }
    th { background:#f9fafb; text-align:left; }
    a { color:#0ea5e9; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .small { font-size:9pt; color:#6b7280; }
    .score { font-weight: 600; }
    """

    topics_html = "".join(f"<span class='pill'>{t}</span>" for t in topics)

    rows_html = []
    for idx, it in enumerate(items, start=1):
        t = it.get("title") or f"Nota {idx}"
        url = it.get("url") or it.get("link") or ""
        src = it.get("source") or ""
        pub = it.get("pubDate") or ""
        llm = it.get("llm") or {}
        it_sum = llm.get("summary") or it.get("summary") or ""
        it_label = llm.get("sentiment_label")
        it_score = score_to_pct(llm.get("sentiment_score"))
        score_txt = f"{it_score}%" if it_score is not None else "N/A"
        label_txt = it_label or "N/A"

        row = f"""
        <tr>
          <td style='width:24pt;'>{idx}</td>
          <td><div><a href='{url}'>{t}</a></div><div class='small'>{src} · {pub}</div></td>
          <td>{it_sum}</td>
          <td class='score'>{label_txt} ({score_txt})</td>
        </tr>
        """
        rows_html.append(row)

    rows_html_str = "\n".join(rows_html)

    created = getattr(campaign, "createdAt", None)
    created_txt = created.isoformat() if hasattr(created, "isoformat") else str(created)

    html = f"""
    <html>
      <head>
        <meta charset='utf-8' />
        <style>{css}</style>
      </head>
      <body>
        <h1>Reporte de Campaña – {campaign.name}</h1>
        <div class='muted'>Creada: {created_txt} · País: {campaign.country or 'N/A'} · Idioma: {campaign.lang or 'N/A'}</div>

        <h2>Resumen General</h2>
        <div class='box'>
          <div><strong>Sentimiento:</strong> {sentiment_label or 'N/A'} {f'({sentiment_score}%)' if sentiment_score is not None else ''}</div>
          <div style='margin-top:6pt; white-space:pre-wrap;'>{summary}</div>
          {'<div style="margin-top:8pt;">' + topics_html + '</div>' if topics_html else ''}
        </div>

        <h2>Artículos Analizados</h2>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Título</th>
              <th>Resumen</th>
              <th>Sentimiento</th>
            </tr>
          </thead>
          <tbody>
            {rows_html_str}
          </tbody>
        </table>
      </body>
    </html>
    """
    return html


@router.get("/{campaign_id}")
async def report_from_campaign(
    campaign_id: str,
    request: Request,
    x_user_id: Optional[str] = Header(default=None),
    x_admin: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_session),
):
    # 1) Cargar campaña y autorizar
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if not (x_admin == "true" or (x_user_id and x_user_id == campaign.userId)):
        raise HTTPException(status_code=403, detail="Forbidden")

    # 2) Buscar noticias y hacer micro-análisis rápido
    articles = await fetch_google_news(
        q=campaign.query,
        size=campaign.size or 25,
        days_back=campaign.days_back or 14,
        lang=campaign.lang or "es-419",
        country=campaign.country or "MX",
    )

    summarized_items: List[Dict[str, Any]] = []
    for art in articles:
        title = art.get("title") or ""
        link = art.get("link") or ""
        try:
            llm = await analyze_snippet(title=title, summary=f"Enlace: {link}", actor=campaign.query)
        except Exception as e:
            llm = {"summary": f"No se pudo analizar esta nota: {e}"}
        summarized_items.append({
            "title": title,
            "url": link,
            "pubDate": art.get("pubDate"),
            "source": art.get("source"),
            "llm": llm,
        })

    # 3) Resumen global
    joined = "\n".join(f"- {it['title']}" for it in summarized_items if it.get("title"))
    try:
        agg = await analyze_snippet(
            title=f"Resumen global de cobertura sobre: {campaign.query}",
            summary=f"Titulares recientes:\n{joined}",
            actor=campaign.query,
        )
    except Exception as e:
        agg = {"summary": f"No fue posible generar el resumen agregado: {e}", "topics": [], "sentiment_label": None, "sentiment_score": None}

    # 4) Renderizar HTML y devolver PDF
    html = render_html_report(campaign, overall=agg, items=summarized_items)

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    HTML(string=html).write_pdf(tmp.name)

    return FileResponse(
        tmp.name,
        media_type="application/pdf",
        filename=f"reporte_{campaign_id}.pdf",
    )


@router.post("/from-analysis")
async def report_from_client_analysis(
    payload: Dict[str, Any] = Body(..., description="{ campaign: {...}, analysis: {...} }"),
    x_user_id: Optional[str] = Header(default=None),
    x_admin: Optional[str] = Header(default=None),
):
    """
    Alternativa: el frontend envía el objeto `campaign` y `analysis` ya calculado
    para generar el PDF sin volver a llamar al LLM.
    Estructura esperada:
      {
        "campaign": {"id":..., "name":..., "query":..., "country":..., "lang":..., "createdAt":...},
        "analysis": {"overall": {...}, "items": [...]}
      }
    """
    campaign_dict = payload.get("campaign") or {}
    analysis = payload.get("analysis") or {}

    # Validación mínima
    if not campaign_dict:
        raise HTTPException(status_code=400, detail="Missing campaign in payload")

    # Construimos un objeto sencillo tipo Campaign-like para el render
    class DummyCampaign:
        def __init__(self, d: Dict[str, Any]):
            self.id = d.get("id")
            self.name = d.get("name")
            self.query = d.get("query")
            self.size = d.get("size")
            self.days_back = d.get("days_back")
            self.lang = d.get("lang")
            self.country = d.get("country")
            self.userId = d.get("userId")
            self.createdAt = d.get("createdAt")

    campaign_obj = DummyCampaign(campaign_dict)

    overall = analysis.get("overall") or {
        "summary": analysis.get("summary"),
        "sentiment_label": analysis.get("sentiment_label"),
        "sentiment_score": analysis.get("sentiment_score"),
        "topics": analysis.get("topics") or [],
    }

    items = analysis.get("items") or analysis.get("results") or analysis.get("articles") or []

    # Normalizamos campos por si los items vienen de distintas formas
    norm_items: List[Dict[str, Any]] = []
    for it in items:
        norm_items.append({
            "title": it.get("title") or it.get("headline"),
            "url": it.get("url") or it.get("link"),
            "pubDate": it.get("pubDate"),
            "source": it.get("source"),
            "llm": it.get("llm") or {"summary": it.get("summary"), "sentiment_label": it.get("sentiment_label"), "sentiment_score": it.get("sentiment_score")},
        })

    html = render_html_report(campaign_obj, overall=overall, items=norm_items)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    HTML(string=html).write_pdf(tmp.name)

    return FileResponse(
        tmp.name,
        media_type="application/pdf",
        filename=f"reporte_{campaign_obj.id or 'campaign'}.pdf",
    )
