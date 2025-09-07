# app/services/report.py
from __future__ import annotations
import datetime as dt
import urllib.parse
import httpx
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from app.services.llm import analyze_snippet  # la misma que usa /ai/analyze-news
from playwright.async_api import async_playwright


async def _fetch_google_news(q: str, size: int, days_back: int, lang: str, country: str) -> List[Dict[str, Any]]:
    encoded_q = urllib.parse.quote_plus(q)
    url = f"https://news.google.com/rss/search?q={encoded_q}&hl={lang}&gl={country}&ceid={country}:{lang}"

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
        s2 = item.find("source")
        if s2 is not None and s2.text:
            source = s2.text.strip()

        items.append({"title": title, "link": link, "pubDate": pubDate, "source": source})

    if days_back and days_back > 0:
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=days_back)
        filtered = []
        for it in items:
            try:
                parsed = dt.datetime.strptime(it["pubDate"], "%a, %d %b %Y %H:%M:%S %Z")
            except Exception:
                parsed = None
            if parsed is None or parsed >= cutoff:
                filtered.append(it)
        items = filtered

    return items[: max(1, min(size, 100))]


def _esc(s: Optional[str]) -> str:
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _pct_from(score: Optional[float], pct: Optional[float]) -> Optional[int]:
    if isinstance(pct, (int, float)):
        return round(float(pct))
    if isinstance(score, (int, float)):
        return round(((float(score) + 1.0) / 2.0) * 100.0)
    return None


async def generate_report_pdf(*, q: str, size: str = "A4", days_back: int = 14, lang: str = "es-419", country: str = "MX") -> bytes:
    # 1) Buscar noticias
    articles = await _fetch_google_news(q=q, size=25, days_back=days_back, lang=lang, country=country)

    # 2) LLM por item
    summarized_items: List[Dict[str, Any]] = []
    for art in articles:
        title = art.get("title") or ""
        link = art.get("link") or ""
        try:
            ai = await analyze_snippet(
                title=title.strip(),
                summary=f"Enlace: {link}",
                actor=q,
            )
            summarized_items.append({
                "title": title,
                "url": link,
                "pubDate": art.get("pubDate"),
                "source": art.get("source"),
                "llm": ai,  # {summary, sentiment_label, sentiment_score, topics, perception...}
            })
        except Exception as e:
            summarized_items.append({
                "title": title,
                "url": link,
                "pubDate": art.get("pubDate"),
                "source": art.get("source"),
                "llm_error": str(e),
            })

    # 3) Bloque agregado (overall)
    overall = {}
    try:
        joined_titles = "\n".join(f"- {it['title']}" for it in summarized_items if it.get("title"))
        agg = await analyze_snippet(
            title=f"Resumen global de cobertura sobre: {q}",
            summary=f"Titulares recientes:\n{joined_titles}",
            actor=q,
        )
        overall = {
            "summary": agg.get("summary"),
            "sentiment_label": agg.get("sentiment_label"),
            "sentiment_score": agg.get("sentiment_score"),
            "topics": agg.get("topics") or [],
        }
    except Exception as e:
        overall = {
            "summary": f"No fue posible generar el resumen agregado: {e}",
            "sentiment_label": None,
            "sentiment_score": None,
            "topics": [],
        }

    # 4) HTML del reporte (mismo look&feel que el front)
    overall_pct = _pct_from(overall.get("sentiment_score"), overall.get("sentiment_score_pct"))
    topics_html = "".join(f'<span class="topic">{_esc(t)}</span>' for t in (overall.get("topics") or []))

    items_html = []
    for idx, it in enumerate(summarized_items[:50]):
        ai = it.get("llm") or {}
        it_pct = _pct_from(ai.get("sentiment_score"), ai.get("sentiment_score_pct"))
        it_label = ai.get("sentiment_label")
        short = ai.get("summary") or ""
        source = it.get("source") or ""
        url = it.get("url") or ""

        items_html.append(f"""
          <div class="item">
            <div class="item-title">{_esc(it.get('title') or f'Nota {idx+1}')}</div>
            <div class="item-meta">
              {f'<span class="tag">{_esc(it_label)}</span>' if it_label else ''}
              {f'<span class="tag pct">{it_pct}%</span>' if it_pct is not None else ''}
              {f'<span class="source">{_esc(source)}</span>' if source else ''}
              {f'<a class="url" href="{_esc(url)}" target="_blank" rel="noreferrer">Abrir</a>' if url else ''}
            </div>
            {f'<div class="item-summary">{_esc(short)}</div>' if short else ''}
          </div>
        """)

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>{_esc(q)} — Reporte</title>
  <style>
    :root {{
      --brand: #059669;
      --ink: #0f172a;
      --muted: #64748b;
      --border: #e5e7eb;
      --bg: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; padding:24px; font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Arial, Noto Sans; color: var(--ink); background: var(--bg); }}
    .report {{ max-width: 900px; margin: 0 auto; }}
    header {{ display:flex; align-items:center; justify-content:space-between; border-bottom: 1px solid var(--border); padding-bottom: 12px; margin-bottom:16px; }}
    .title {{ font-size: 22px; font-weight: 700; }}
    .meta {{ color: var(--muted); font-size: 12px; }}
    .overall {{ display:grid; grid-template-columns: 1fr 2fr; gap:16px; border:1px solid var(--border); border-radius:10px; padding:16px; margin-bottom:16px; }}
    .box {{ border:1px solid var(--border); border-radius:10px; padding:12px; }}
    .box .label {{ font-size: 11px; color: var(--muted); margin-bottom:4px; }}
    .sentiment {{ font-weight:600; }}
    .topics {{ display:flex; gap:6px; flex-wrap:wrap; }}
    .topic {{ display:inline-block; padding:4px 8px; border-radius:999px; background:#d1fae5; color:#065f46; border:1px solid #a7f3d0; font-size:12px; }}
    h2 {{ margin: 16px 0 8px; font-size:18px; }}
    .item {{ border:1px solid var(--border); border-radius:10px; padding:12px; margin-bottom:10px; }}
    .item-title {{ font-weight:600; margin-bottom:6px; }}
    .item-meta {{ color: var(--muted); font-size:12px; display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:6px; }}
    .tag {{ display:inline-block; padding:2px 6px; border-radius:6px; background:#f1f5f9; color:#334155; border:1px solid #e2e8f0; }}
    .tag.pct {{ background:#ecfeff; color:#075985; border-color:#bae6fd; }}
    .source {{ opacity:.9; }}
    .url {{ color: var(--brand); text-decoration: underline; }}
    .foot {{ color: var(--muted); font-size:11px; text-align:center; margin-top:16px; }}
  </style>
</head>
<body>
  <div class="report">
    <header>
      <div class="title">{_esc(q)}</div>
      <div class="meta">{_esc(dt.datetime.now().isoformat(timespec='minutes'))}</div>
    </header>

    <section class="overall">
      <div class="box">
        <div class="label">Sentimiento</div>
        <div class="sentiment">{_esc(overall.get('sentiment_label') or 'N/A')}</div>
        {f'<div class="meta">Sentimiento: {overall_pct}%</div>' if overall_pct is not None else ''}
      </div>
      <div class="box">
        <div class="label">Resumen</div>
        <div>{_esc(overall.get('summary') or 'Sin resumen.')}</div>
      </div>
    </section>

    {f'<section class="box" style="margin-bottom:16px"><div class="label">Temas relevantes</div><div class="topics">{topics_html}</div></section>' if topics_html else ''}

    <h2>Artículos analizados</h2>
    {''.join(items_html) if items_html else '<div class="meta">No se encontraron artículos.</div>'}

    <div class="foot">BLACKBOX MONITOR — Reporte generado automáticamente</div>
  </div>
</body>
</html>
"""

    # 5) Render a PDF con Playwright/Chromium
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        page = await browser.new_page()
        await page.set_content(html, wait_until="load")
        pdf_bytes = await page.pdf(
            format=size if size in ("A4", "Letter") else "A4",
            print_background=True,
            margin={"top": "20mm", "bottom": "20mm", "left": "16mm", "right": "16mm"},
        )
        await browser.close()
        return pdf_bytes