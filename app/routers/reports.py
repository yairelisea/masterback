from __future__ import annotations

import io
import os
import re
from typing import Any, Dict, Optional, List
from datetime import date, datetime, timedelta
from collections import Counter

import httpx
from fastapi import APIRouter, HTTPException, Request, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from .. import models
from ..models import ActorReport, ReportType
from sqlalchemy.orm import selectinload
from datetime import date, datetime, timedelta
from pydantic import BaseModel, Field
from ..deps import get_current_user

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

    print("Proxying PDF request to:", url)

    try:
        # Use streaming to avoid any transformations; ensure raw bytes.
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            async with client.stream(
                "POST",
                url,
                json=payload,
                headers={"Accept": "application/pdf"},
            ) as resp:
                print(f"PDF service responded with status: {resp.status_code}")
                print(f"Response headers: {resp.headers}")
                print(f"Response Content-Type: {resp.headers.get('Content-Type')}")
                print(f"Response Content-Disposition: {resp.headers.get('Content-Disposition')}")
                print(resp.stream)
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
                print(f"Received {len(chunks)} chunks from PDF service")
                pdf_bytes = b"".join(chunks)

                print(f"Received PDF response, size: {len(pdf_bytes)} bytes")

                # Validate magic header
                _assert_pdf_bytes(pdf_bytes)

                # Try to get filename from Content-Disposition
                disp = resp.headers.get("Content-Disposition") or resp.headers.get("content-disposition") or ""
                filename_from_service = _extract_filename(disp)
                final_name = safe_filename(filename_from_service or suggested_name)

                print(f"Generated PDF report: {final_name}, size: {len(pdf_bytes)} bytes")

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

def parse_date(date_str: str) -> date:
    """Convert string date to date object. Accepts YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format. Use YYYY-MM-DD format. Error: {str(e)}"
        )

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
    campaignId: str = Field(..., description="Campaign ID")
    reportDate: str = Field(
        default_factory=lambda: date.today().isoformat(),
        description="Report date in YYYY-MM-DD format"
    )

@router.post("/daily-news")
async def daily_news_report(
    payload: DailyNewsReportRequest,
    db: AsyncSession = Depends(get_session),
):
    """
    Generates a PDF report for the daily news of a campaign.
    """
    report_date = parse_date(payload.reportDate)

    print(f"Received payload: {payload}")
    campaign = await db.get(models.Campaign, payload.campaignId)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Fetch items and analyses for the specified date
    # start_of_day = datetime.combine(payload.reportDate, datetime.min.time())
    # end_of_day = datetime.combine(payload.reportDate, datetime.max.time())
    start_of_day = datetime.combine(report_date, datetime.min.time())
    end_of_day = datetime.combine(report_date, datetime.max.time())

    print(start_of_day)
    print(end_of_day)

    # items_q = (
    #     select(models.IngestedItem)
    #     .where(
    #        models.IngestedItem.campaignId == payload.campaignId,
    #         models.IngestedItem.createdAt >= start_of_day,
    #        models.IngestedItem.createdAt <= end_of_day,
    #     )
    #     .order_by(models.IngestedItem.createdAt.desc())
    # )
    # items = (await db.execute(items_q)).scalars().all()
    # Modificada la consulta para incluir analysis
    items_q = (
        select(models.IngestedItem)
        .options(selectinload(models.IngestedItem.analysis))  # Añadir esta línea
        .where(
            models.IngestedItem.campaignId == payload.campaignId,
            models.IngestedItem.createdAt >= start_of_day,
            models.IngestedItem.createdAt <= end_of_day,
        )
        .order_by(models.IngestedItem.createdAt.desc())
    )
    items = (await db.execute(items_q)).scalars().all()

    print(f"Fetched {len(items)} items for report.")

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
                #"key_points": item.analysis.key_points,
            })

    pdf_payload = {
        "report_type": "daily_news",
        "campaign": {
            "name": campaign.name,
            "query": campaign.query,
        },
        "report_date": report_date.isoformat(), #payload.reportDate.isoformat(),
        "items": report_items,
    }



    suggested_name = f"Reporte_Diario_{campaign.name}_{report_date.isoformat()}"
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


# ============================================================================
# ENDPOINTS PARA REPORTES HISTÓRICOS (ActorReport)
# ============================================================================

class ReportOut(BaseModel):
    """Schema de salida para reportes históricos"""
    id: str
    actorName: str
    reportType: str
    summary: Optional[str]
    itemCount: Optional[int]
    createdAt: datetime
    reportData: Optional[Dict[str, Any]] = None  # Solo se incluye en detalle

    class Config:
        from_attributes = True


class GenerateReportRequest(BaseModel):
    """Request para generar un reporte on-demand"""
    campaignId: str
    reportType: str = Field(..., description="'daily' o 'weekly'")
    reportDate: Optional[str] = Field(None, description="Fecha del reporte (YYYY-MM-DD). Default: ayer para daily, domingo pasado para weekly")


@router.get("/campaigns/{campaign_id}/history", response_model=List[ReportOut])
async def list_campaign_reports(
    campaign_id: str,
    report_type: Optional[str] = Query(None, description="Filtrar por tipo: 'daily' o 'weekly'"),
    limit: int = Query(30, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Lista los reportes históricos de una campaña.

    - **campaign_id**: ID de la campaña
    - **report_type**: Filtrar por 'daily' o 'weekly' (opcional)
    - **limit**: Número máximo de reportes a retornar (default: 30)
    """
    # Verificar que la campaña existe y pertenece al usuario
    campaign = await db.get(models.Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.userId != current_user["id"] and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    # Construir query
    query = (
        select(ActorReport)
        .where(ActorReport.actorName == campaign.query)
        .order_by(desc(ActorReport.createdAt))
        .limit(limit)
    )

    # Filtrar por tipo si se especifica
    if report_type:
        try:
            rt = ReportType(report_type.lower())
            query = query.where(ActorReport.reportType == rt)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de reporte inválido. Usa 'daily' o 'weekly'"
            )

    result = await db.execute(query)
    reports = result.scalars().all()

    # Convertir a schema sin incluir reportData completo (es muy grande)
    return [
        ReportOut(
            id=r.id,
            actorName=r.actorName,
            reportType=r.reportType.value,
            summary=r.summary,
            itemCount=r.itemCount,
            createdAt=r.createdAt,
            reportData=None,  # No incluir datos completos en listado
        )
        for r in reports
    ]


@router.get("/campaigns/{campaign_id}/history/{report_id}", response_model=ReportOut)
async def get_campaign_report(
    campaign_id: str,
    report_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Obtiene el detalle completo de un reporte específico.

    Incluye todos los datos del reporte (reportData).
    """
    # Verificar campaña
    campaign = await db.get(models.Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.userId != current_user["id"] and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    # Obtener reporte
    report = await db.get(ActorReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")

    # Verificar que el reporte pertenece a esta campaña
    if report.actorName != campaign.query:
        raise HTTPException(status_code=404, detail="Report not found for this campaign")

    return ReportOut(
        id=report.id,
        actorName=report.actorName,
        reportType=report.reportType.value,
        summary=report.summary,
        itemCount=report.itemCount,
        createdAt=report.createdAt,
        reportData=report.reportData,  # Incluir datos completos
    )


@router.get("/campaigns/{campaign_id}/latest")
async def get_latest_reports(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Obtiene el reporte diario y semanal más reciente de una campaña.

    Útil para mostrar en el dashboard.
    """
    # Verificar campaña
    campaign = await db.get(models.Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.userId != current_user["id"] and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    # Obtener último reporte diario
    daily_query = (
        select(ActorReport)
        .where(
            ActorReport.actorName == campaign.query,
            ActorReport.reportType == ReportType.DAILY,
        )
        .order_by(desc(ActorReport.createdAt))
        .limit(1)
    )
    daily_result = await db.execute(daily_query)
    latest_daily = daily_result.scalar_one_or_none()

    # Obtener último reporte semanal
    weekly_query = (
        select(ActorReport)
        .where(
            ActorReport.actorName == campaign.query,
            ActorReport.reportType == ReportType.WEEKLY,
        )
        .order_by(desc(ActorReport.createdAt))
        .limit(1)
    )
    weekly_result = await db.execute(weekly_query)
    latest_weekly = weekly_result.scalar_one_or_none()

    return {
        "daily": {
            "id": latest_daily.id if latest_daily else None,
            "summary": latest_daily.summary if latest_daily else None,
            "createdAt": latest_daily.createdAt.isoformat() if latest_daily else None,
            "data": latest_daily.reportData if latest_daily else None,
        } if latest_daily else None,
        "weekly": {
            "id": latest_weekly.id if latest_weekly else None,
            "summary": latest_weekly.summary if latest_weekly else None,
            "createdAt": latest_weekly.createdAt.isoformat() if latest_weekly else None,
            "data": latest_weekly.reportData if latest_weekly else None,
        } if latest_weekly else None,
    }


@router.post("/generate")
async def generate_report_on_demand(
    payload: GenerateReportRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Genera un reporte on-demand (diario o semanal).

    Útil para regenerar reportes o generar reportes de fechas específicas.

    - **campaignId**: ID de la campaña
    - **reportType**: 'daily' o 'weekly'
    - **reportDate**: Fecha del reporte (opcional, default: ayer/domingo pasado)
    """
    from ..services.campaign_report_service import (
        generate_and_save_daily_report,
        generate_and_save_weekly_report,
    )

    # Verificar campaña
    campaign = await db.get(models.Campaign, payload.campaignId)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Solo admin o dueño puede generar reportes
    if campaign.userId != current_user["id"] and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    # Parsear fecha si se proporciona
    report_date = None
    if payload.reportDate:
        try:
            report_date = datetime.strptime(payload.reportDate, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usa YYYY-MM-DD")

    try:
        if payload.reportType.lower() == "daily":
            if report_date is None:
                report_date = date.today() - timedelta(days=1)  # Ayer

            result = await generate_and_save_daily_report(
                campaign_id=payload.campaignId,
                report_date=report_date,
                db=db,
            )

        elif payload.reportType.lower() == "weekly":
            if report_date is None:
                # Calcular el domingo pasado
                today = date.today()
                days_since_sunday = (today.weekday() + 1) % 7
                if days_since_sunday == 0:
                    days_since_sunday = 7
                report_date = today - timedelta(days=days_since_sunday)

            result = await generate_and_save_weekly_report(
                campaign_id=payload.campaignId,
                week_end_date=report_date,
                db=db,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Tipo de reporte inválido. Usa 'daily' o 'weekly'"
            )

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando reporte: {str(e)}")


@router.post("/campaigns/{campaign_id}/daily-pdf")
async def generate_daily_pdf(
    campaign_id: str,
    report_date: str = Query(None, description="Fecha del reporte (YYYY-MM-DD)"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Genera un PDF del reporte diario más reciente o de una fecha específica.
    """
    from ..services.campaign_report_service import generate_daily_report

    # Verificar campaña
    campaign = await db.get(models.Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.userId != current_user["id"] and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    # Parsear fecha
    if report_date:
        try:
            parsed_date = datetime.strptime(report_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido")
    else:
        parsed_date = date.today() - timedelta(days=1)

    # Generar reporte (sin guardar)
    report_data = await generate_daily_report(campaign_id, parsed_date, db)

    # Preparar payload para PDF
    pdf_payload = {
        "report_type": "daily_comprehensive",
        "campaign": report_data["campaign"],
        "report_date": report_data["report_date"],
        "summary": report_data["summary"],
        "news": report_data["news"],
        "social": report_data["social"],
        "topics": report_data["topics"],
        "risk_alerts": report_data["risk_alerts"],
    }

    suggested_name = f"Reporte_Diario_{campaign.name}_{parsed_date.isoformat()}"
    return await _proxy_pdf_service(pdf_payload, suggested_name)


@router.post("/campaigns/{campaign_id}/weekly-pdf")
async def generate_weekly_pdf(
    campaign_id: str,
    week_end_date: str = Query(None, description="Último día de la semana (YYYY-MM-DD)"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """
    Genera un PDF del reporte semanal más reciente o de una semana específica.
    """
    from ..services.campaign_report_service import generate_weekly_report

    # Verificar campaña
    campaign = await db.get(models.Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    if campaign.userId != current_user["id"] and current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")

    # Parsear fecha
    if week_end_date:
        try:
            parsed_date = datetime.strptime(week_end_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de fecha inválido")
    else:
        # Calcular domingo pasado
        today = date.today()
        days_since_sunday = (today.weekday() + 1) % 7
        if days_since_sunday == 0:
            days_since_sunday = 7
        parsed_date = today - timedelta(days=days_since_sunday)

    # Generar reporte (sin guardar)
    report_data = await generate_weekly_report(campaign_id, parsed_date, db)

    # Preparar payload para PDF
    pdf_payload = {
        "report_type": "weekly_comprehensive",
        "campaign": report_data["campaign"],
        "period": report_data["period"],
        "summary": report_data["summary"],
        "comparison": report_data["comparison"],
        "daily_trend": report_data["daily_trend"],
        "news": report_data["news"],
        "social": report_data["social"],
        "topics": report_data["topics"],
        "narratives": report_data.get("narratives", []),
        "risk_analysis": report_data["risk_analysis"],
        "insights": report_data["insights"],
    }

    suggested_name = f"Reporte_Semanal_{campaign.name}_{report_data['period']['start_date']}_{report_data['period']['end_date']}"
    return await _proxy_pdf_service(pdf_payload, suggested_name)