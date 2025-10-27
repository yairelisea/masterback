from __future__ import annotations

import io
import os
import re
from typing import Any, Dict, Optional, List
from datetime import date, datetime, timedelta
from collections import Counter

import httpx
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from .. import models

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
async def post_report(payload: Dict[str, Any], request: Request, db: AsyncSession = Depends(get_session)):
    """
    Accepts JSON payload from the front-end and returns a generated PDF.
    This endpoint can auto-build the minimal payload from the DB if a campaignId is provided.
    Expected minimal payload:
    {
      "campaignId": "..."  # optional if full payload is provided
      "campaign": {"name": "...", "query": "..."},
      "analysis": {...}
    }
    """
    # 1) lee payload existente como hoy
    data: Dict[str, Any] = payload or {}

    # 2) si viene campaignId y falta info, arma desde BD
    campaign_id = data.get("campaignId")
    if campaign_id:
        c = await db.get(models.Campaign, campaign_id)
        if not c:
            raise HTTPException(status_code=404, detail="Campaign not found")

        # items + analyses recientes
        items_q = (
            select(models.IngestedItem)
            .where(models.IngestedItem.campaignId == campaign_id)
            .order_by(models.IngestedItem.publishedAt.desc().nullslast(), models.IngestedItem.createdAt.desc())
            .limit(200)
        )
        analyses_q = (
            select(models.Analysis)
            .where(models.Analysis.campaignId == campaign_id)
            .order_by(models.Analysis.createdAt.desc())
            .limit(200)
        )
        items = (await db.execute(items_q)).scalars().all()
        analyses = (await db.execute(analyses_q)).scalars().all()

        # arma estructura mínima que entiende tu microservicio PDF
        data.setdefault("campaign", {
            "name": c.name, "query": c.query, "country": c.country, "lang": c.lang,
            "size": c.size, "days_back": c.days_back,
        })
        data.setdefault("analysis", {})
        data["analysis"].setdefault("items", [
            {
                "title": it.title,
                "url": it.url,
                "publishedAt": (it.publishedAt.isoformat() if it.publishedAt else None)
            } for it in items
        ])
        data["analysis"].setdefault("analyses", [
            {
                "sentiment": a.sentiment,
                "tone": a.tone,
                "topics": a.topics,
                "summary": a.summary,
                "stance": a.stance,
                "createdAt": (a.createdAt.isoformat() if a.createdAt else None)
            } for a in analyses
        ])

    # 3) continúa con el render PDF como ya lo haces
    campaign = data.get("campaign") or {}
    analysis = data.get("analysis") or {}
    if not analysis:
        raise HTTPException(status_code=400, detail="analysis es requerido")

    suggested_name = (campaign.get("name") or campaign.get("query") or "Reporte").strip() or "Reporte"
    return await _proxy_pdf_service(data, suggested_name)

class DailyNewsReportRequest(BaseModel):
    campaignId: str
    reportDate: date = date.today()

@router.post("/daily-news")
async def daily_news_report(
    payload: DailyNewsReportRequest,
    db: AsyncSession = Depends(get_session),
):
    """
    Generates a PDF report for the daily news of a campaign.
    """
    campaign = await db.get(models.Campaign, payload.campaignId)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Fetch items and analyses for the specified date
    start_of_day = datetime.combine(payload.reportDate, datetime.min.time())
    end_of_day = datetime.combine(payload.reportDate, datetime.max.time())

    items_q = (
        select(models.IngestedItem)
        .where(
            models.IngestedItem.campaignId == payload.campaignId,
            models.IngestedItem.createdAt >= start_of_day,
            models.IngestedItem.createdAt <= end_of_day,
        )
        .order_by(models.IngestedItem.createdAt.desc())
    )
    items = (await db.execute(items_q)).scalars().all()

    # Prepare data for the PDF service
    report_items = []
    for item in items:
        if item.analysis:
            report_items.append({
                "title": item.title,
                "url": item.url,
                "publishedAt": item.publishedAt.isoformat() if item.publishedAt else None,
                "summary": item.analysis.summary,
                "sentiment_label": item.analysis.tone,
                "sentiment_score": item.analysis.sentiment,
                "topics": item.analysis.topics,
                "key_points": item.analysis.key_points,
            })

    pdf_payload = {
        "report_type": "daily_news",
        "campaign": {
            "name": campaign.name,
            "query": campaign.query,
        },
        "report_date": payload.reportDate.isoformat(),
        "items": report_items,
    }

    suggested_name = f"Reporte_Diario_{campaign.name}_{payload.reportDate.isoformat()}"
    return await _proxy_pdf_service(pdf_payload, suggested_name)

class DigitalPerceptionReportRequest(BaseModel):
    campaignId: str
    startDate: date
    endDate: date = date.today()

@router.post("/digital-perception")
async def digital_perception_report(
    payload: DigitalPerceptionReportRequest,
    db: AsyncSession = Depends(get_session),
):
    """
    Generates a PDF report for the digital perception of a campaign over a date range.
    """
    campaign = await db.get(models.Campaign, payload.campaignId)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Fetch analyses for the specified date range
    start_of_day = datetime.combine(payload.startDate, datetime.min.time())
    end_of_day = datetime.combine(payload.endDate, datetime.max.time())

    analyses_q = (
        select(models.Analysis)
        .where(
            models.Analysis.campaignId == payload.campaignId,
            models.Analysis.createdAt >= start_of_day,
            models.Analysis.createdAt <= end_of_day,
        )
    )
    analyses = (await db.execute(analyses_q)).scalars().all()

    # Process data for the report
    sentiment_by_day = {}
    all_topics = []
    total_sentiment_score = 0

    for analysis in analyses:
        day = analysis.createdAt.date()
        if day not in sentiment_by_day:
            sentiment_by_day[day] = {"Positivo": 0, "Negativo": 0, "Neutral": 0}
        
        if analysis.tone in sentiment_by_day[day]:
            sentiment_by_day[day][analysis.tone] += 1

        if analysis.topics:
            all_topics.extend(analysis.topics)
        
        if analysis.sentiment:
            total_sentiment_score += analysis.sentiment

    # Convert dates to strings for the payload
    sentiment_trend = [
        {"date": day.isoformat(), **counts} for day, counts in sorted(sentiment_by_day.items())
    ]

    topic_frequency = [{"topic": topic, "count": count} for topic, count in Counter(all_topics).most_common(10)]

    average_sentiment = total_sentiment_score / len(analyses) if analyses else 0

    pdf_payload = {
        "report_type": "digital_perception",
        "campaign": {
            "name": campaign.name,
            "query": campaign.query,
        },
        "start_date": payload.startDate.isoformat(),
        "end_date": payload.endDate.isoformat(),
        "summary": {
            "total_articles": len(analyses),
            "average_sentiment": round(average_sentiment, 2),
        },
        "sentiment_trend": sentiment_trend,
        "topic_frequency": topic_frequency,
    }

    suggested_name = f"Reporte_Percepcion_{campaign.name}_{payload.startDate.isoformat()}_{payload.endDate.isoformat()}"
    return await _proxy_pdf_service(pdf_payload, suggested_name)