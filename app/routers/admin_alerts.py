# app/routers/admin_alerts.py
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..db import get_session
from .. import models
from ..scheduler import schedule_alert, run_alert

router = APIRouter(prefix="/admin/alerts", tags=["admin:alerts"])

async def require_admin(x_admin: Optional[str] = Header(default=None)):
    if x_admin != "true":
        raise HTTPException(status_code=403, detail="Admin requerido")
    return True

class AlertIn(BaseModel):
    userId: str
    campaignId: Optional[str] = None
    name: str = Field(min_length=2, max_length=160)
    scheduleCron: str = Field(default="0 12 * * *")   # diario 12:00
    timezone: str = Field(default="America/Monterrey")
    analyze: bool = True
    isActive: bool = True

class AlertOut(AlertIn):
    id: str

class AlertQueryIn(BaseModel):
    q: str
    country: str = "MX"
    lang: str = "es-419"
    daysBack: int = Field(ge=1, le=90, default=14)
    size: int = Field(ge=1, le=100, default=35)
    cityKeywords: Optional[List[str]] = None

class AlertQueryOut(AlertQueryIn):
    id: str
    alertId: str

@router.post("", response_model=AlertOut, dependencies=[Depends(require_admin)])
async def create_alert(payload: AlertIn, session: AsyncSession = Depends(get_session)):
    a = models.Alert(**payload.dict())
    session.add(a)
    await session.commit()
    await session.refresh(a)
    # programar job
    await schedule_alert(a)
    return AlertOut(id=a.id, **payload.dict())

@router.get("", response_model=List[AlertOut], dependencies=[Depends(require_admin)])
async def list_alerts(session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(models.Alert))
    out = []
    for a in res.scalars().all():
        out.append(AlertOut(
            id=a.id, userId=a.userId, campaignId=a.campaignId, name=a.name,
            scheduleCron=a.scheduleCron, timezone=a.timezone, analyze=a.analyze, isActive=a.isActive
        ))
    return out

@router.post("/{alert_id}/queries", response_model=AlertQueryOut, dependencies=[Depends(require_admin)])
async def add_query(alert_id: str, payload: AlertQueryIn, session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(models.Alert).where(models.Alert.id == alert_id))
    a = res.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    aq = models.AlertQuery(alertId=alert_id, **payload.dict())
    session.add(aq)
    await session.commit()
    await session.refresh(aq)
    return AlertQueryOut(id=aq.id, alertId=aq.alertId, **payload.dict())

@router.post("/{alert_id}/run-now", dependencies=[Depends(require_admin)])
async def run_now(alert_id: str, session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(models.Alert).where(models.Alert.id == alert_id))
    a = res.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    await run_alert(a)
    return {"ok": True}

@router.get("/{alert_id}/notifications", dependencies=[Depends(require_admin)])
async def list_notifications(alert_id: str, session: AsyncSession = Depends(get_session)):
    res = await session.execute(
        select(models.AlertNotification).where(models.AlertNotification.alertId == alert_id).order_by(models.AlertNotification.createdAt.desc())
    )
    rows = res.scalars().all()
    return [
        {
            "id": n.id,
            "createdAt": n.createdAt,
            "itemsCount": n.itemsCount,
            "aggregate": n.aggregate
        } for n in rows
    ]
