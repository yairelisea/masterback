from __future__ import annotations
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session, SessionLocal
from ..deps import get_current_user
from ..models import Campaign, User, PlanTier, Analysis, IngestedItem, ItemStatus
from ..schemas import (
    AdminUserOut,
    CampaignOut,
    PlanTierEnum,
)
from ..schemas import IngestedItemOut, AnalysisOut
from sqlalchemy import func

router = APIRouter(prefix="/admin", tags=["admin-tools"])


# -----------------------------
# Auth dependency: admin only
# -----------------------------
async def get_current_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user:
        raise HTTPException(status_code=401, detail="Missing token")
    if user.get("role") != "admin":
        raise HTTPException(status_code=401, detail="Admin token required")
    return user


# -----------------------------
# Pydantic models (admin I/O)
# -----------------------------
class AdminUserCreateIn(BaseModel):
    email: str
    name: Optional[str] = None
    plan: PlanTierEnum = PlanTierEnum.BASIC
    features: Optional[Dict[str, Any]] = None
    isAdmin: bool = False


class AdminUserPatchIn(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None


class PlanUpdateIn(BaseModel):
    plan: PlanTierEnum


class FeaturesUpdateIn(BaseModel):
    features: Dict[str, Any] = Field(default_factory=dict)


class AdminCampaignCreateIn(BaseModel):
    # name no fue listado, pero Campaign lo requiere; lo hacemos opcional con fallback.
    name: Optional[str] = None
    query: str
    size: int = 25
    days_back: int = Field(14, alias="days_back")
    lang: str = "es-419"
    country: str = "MX"
    city_keywords: Optional[list[str]] = None
    plan: PlanTierEnum = PlanTierEnum.BASIC
    autoEnabled: bool = True

    class Config:
        populate_by_name = True


class AdminCampaignPatchIn(BaseModel):
    size: Optional[int] = None
    days_back: Optional[int] = Field(default=None, alias="days_back")
    autoEnabled: Optional[bool] = None
    plan: Optional[PlanTierEnum] = None

    class Config:
        populate_by_name = True


class AssignCampaignIn(BaseModel):
    userId: str


# -----------------------------
# Helpers
# -----------------------------
def _to_user_out(u: User) -> AdminUserOut:
    return AdminUserOut.model_validate(u)


def _to_campaign_out(c: Campaign) -> CampaignOut:
    return CampaignOut.model_validate(c)


# -----------------------------
# Users (Admin)
# -----------------------------
@router.get("/users", response_model=list[AdminUserOut])
async def admin_list_users(
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    q = select(User).order_by(User.createdAt.desc())
    rows = (await db.execute(q)).scalars().all()
    return [_to_user_out(u) for u in rows]


@router.post("/users", response_model=AdminUserOut)
async def admin_create_user(
    payload: AdminUserCreateIn,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    # unique email check
    existing = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")

    new_user = User(
        id=str(uuid.uuid4()),
        email=payload.email,
        name=payload.name or payload.email.split("@")[0],
        isAdmin=payload.isAdmin,
        plan=PlanTier(payload.plan.value),
        features=payload.features or None,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return _to_user_out(new_user)


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def admin_patch_user(
    user_id: str,
    payload: AdminUserPatchIn,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.email is not None:
        user.email = payload.email
    if payload.name is not None:
        user.name = payload.name
    await db.commit()
    await db.refresh(user)
    return _to_user_out(user)


@router.put("/users/{user_id}/plan", response_model=AdminUserOut)
async def admin_update_user_plan(
    user_id: str,
    payload: PlanUpdateIn,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.plan = PlanTier(payload.plan.value)
    await db.commit()
    await db.refresh(user)
    return _to_user_out(user)


@router.put("/users/{user_id}/features", response_model=AdminUserOut)
async def admin_update_user_features(
    user_id: str,
    payload: FeaturesUpdateIn,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.features = payload.features or None
    await db.commit()
    await db.refresh(user)
    return _to_user_out(user)


# -----------------------------
# Campaigns (Admin)
# -----------------------------
@router.get("/campaigns", response_model=list[CampaignOut])
async def admin_list_campaigns(
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    q = select(Campaign).order_by(Campaign.createdAt.desc())
    rows = (await db.execute(q)).scalars().all()
    return [_to_campaign_out(c) for c in rows]


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
async def admin_get_campaign(
    campaign_id: str,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    camp = await db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _to_campaign_out(camp)


@router.post("/campaigns", response_model=CampaignOut)
async def admin_create_campaign(
    payload: AdminCampaignCreateIn,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    name = payload.name or (payload.query[:80] if payload.query else "Campaña")
    camp = Campaign(
        name=name,
        query=payload.query,
        size=payload.size,
        days_back=payload.days_back,
        lang=payload.lang,
        country=payload.country,
        city_keywords=payload.city_keywords,
        plan=PlanTier(payload.plan.value),
        autoEnabled=payload.autoEnabled,
        userId=None,
    )
    db.add(camp)
    await db.commit()
    await db.refresh(camp)
    return _to_campaign_out(camp)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def admin_patch_campaign(
    campaign_id: str,
    payload: AdminCampaignPatchIn,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    camp = await db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if payload.size is not None:
        camp.size = payload.size
    if payload.days_back is not None:
        camp.days_back = payload.days_back
    if payload.autoEnabled is not None:
        camp.autoEnabled = payload.autoEnabled
    if payload.plan is not None:
        camp.plan = PlanTier(payload.plan.value)
    await db.commit()
    await db.refresh(camp)
    return _to_campaign_out(camp)


@router.post("/campaigns/{campaign_id}/assign", response_model=CampaignOut)
async def admin_assign_campaign(
    campaign_id: str,
    payload: AssignCampaignIn,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    camp = await db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    user = await db.get(User, payload.userId)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    camp.userId = user.id
    await db.commit()
    await db.refresh(camp)
    return _to_campaign_out(camp)


@router.get("/campaigns/{campaign_id}/items", response_model=list[IngestedItemOut])
async def admin_list_campaign_items(
    campaign_id: str,
    page: int = 1,
    per_page: int = 25,
    order: str = "publishedAt",
    dir: str = "desc",
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    camp = await db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    per_page = max(1, min(per_page, 200))
    offset = max(0, (page - 1) * per_page)
    order_col = IngestedItem.publishedAt if order == "publishedAt" else IngestedItem.createdAt
    order_by = order_col.desc() if str(dir).lower() == "desc" else order_col.asc()
    q = (
        select(IngestedItem)
        .where(IngestedItem.campaignId == campaign_id)
        .order_by(order_by)
        .offset(offset)
        .limit(per_page)
    )
    rows = (await db.execute(q)).scalars().all()
    return [IngestedItemOut.model_validate(r) for r in rows]


@router.get("/campaigns/{campaign_id}/analyses", response_model=list[AnalysisOut])
async def admin_list_campaign_analyses(
    campaign_id: str,
    page: int = 1,
    per_page: int = 25,
    order: str = "createdAt",
    dir: str = "desc",
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    camp = await db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    per_page = max(1, min(per_page, 200))
    offset = max(0, (page - 1) * per_page)
    order_col = Analysis.createdAt if order == "createdAt" else Analysis.createdAt
    order_by = order_col.desc() if str(dir).lower() == "desc" else order_col.asc()
    q = (
        select(Analysis)
        .where(Analysis.campaignId == campaign_id)
        .order_by(order_by)
        .offset(offset)
        .limit(per_page)
    )
    rows = (await db.execute(q)).scalars().all()
    return [AnalysisOut.model_validate(r) for r in rows]


@router.get("/campaigns/{campaign_id}/overview")
async def admin_campaign_overview(
    campaign_id: str,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    camp = await db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Items counts by status
    cnt_rows = (
        await db.execute(
            select(IngestedItem.status, func.count())
            .where(IngestedItem.campaignId == campaign_id)
            .group_by(IngestedItem.status)
        )
    ).all()
    counts: Dict[str, int] = {str(s[0].value if s[0] else "NONE"): int(s[1]) for s in cnt_rows}

    # Totals
    total_items = sum(counts.values())
    analyses_count = (
        await db.execute(select(func.count()).select_from(Analysis).where(Analysis.campaignId == campaign_id))
    ).scalar_one()

    # Last timestamps
    last_item_at = (
        await db.execute(
            select(func.max(IngestedItem.createdAt)).where(IngestedItem.campaignId == campaign_id)
        )
    ).scalar_one()
    last_analysis_at = (
        await db.execute(
            select(func.max(Analysis.createdAt)).where(Analysis.campaignId == campaign_id)
        )
    ).scalar_one()

    return {
        "campaign": _to_campaign_out(camp).model_dump(),
        "items": {
            "total": total_items,
            "by_status": counts,
            "last_created_at": last_item_at,
        },
        "analyses": {
            "total": int(analyses_count),
            "last_created_at": last_analysis_at,
        },
    }


# -----------------------------
# Operations (Admin)
# -----------------------------
@router.post("/campaigns/{campaign_id}/recover")
async def admin_recover_campaign(
    campaign_id: str,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    camp = await db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")
    # Usa servicio local de búsqueda (RSS) para recuperar notas relacionadas
    try:
        from ..services.search_local import search_local_news
        items = await search_local_news(
            query=camp.query,
            city=(camp.city_keywords[0] if (camp.city_keywords and len(camp.city_keywords) > 0) else None),
            country=camp.country,
            lang=camp.lang,
            days_back=camp.days_back,
            limit=camp.size,
        )
        return {"count": len(items), "items": items}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recover failed: {e}")


@router.post("/campaigns/{campaign_id}/process")
async def admin_process_campaign(
    campaign_id: str,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    # Reutiliza la lógica existente de analyses_extra.process_pending
    try:
        from .analyses_extra import process_pending as _process_pending
        res = await _process_pending(campaignId=campaign_id, limit=200, db=db)  # type: ignore
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Process failed: {e}")


@router.post("/campaigns/{campaign_id}/report")
async def admin_report_campaign(
    campaign_id: str,
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    camp = await db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Construye un payload sencillo de análisis con últimos items/analyses
    q = (
        select(Analysis, IngestedItem)
        .outerjoin(IngestedItem, IngestedItem.id == Analysis.itemId)
        .where(Analysis.campaignId == campaign_id)
        .order_by(Analysis.createdAt.desc())
        .limit(50)
    )
    pairs = (await db.execute(q)).all()
    items: list[dict] = []
    sentiments: list[float] = []
    topics: list[str] = []
    for a, it in pairs:
        title = (it.title if it else None) or (a.summary or "")
        url = (it.url if it else None)
        if a.sentiment is not None:
            sentiments.append(float(a.sentiment))
        if a.topics:
            try:
                topics.extend([str(t) for t in (a.topics or [])])
            except Exception:
                pass
        items.append({
            "title": title,
            "url": url,
            "llm": {
                "sentiment_score": a.sentiment,
                "summary": a.summary,
                "topics": a.topics,
            },
        })

    avg_sent = (sum(sentiments) / len(sentiments)) if sentiments else None
    analysis_payload = {
        "sentiment_score": avg_sent,
        "sentiment_label": (
            "positivo" if (avg_sent is not None and avg_sent > 0.2) else (
                "negativo" if (avg_sent is not None and avg_sent < -0.2) else "neutral"
            ) if avg_sent is not None else None
        ),
        "summary": None,
        "topics": list(dict.fromkeys(topics))[:10] if topics else [],
        "items": items,
    }

    # Usa el router de reports para generar PDF (o HTML fallback) vía microservicio
    try:
        from .reports import _proxy_pdf_service, safe_filename
        campaign_info = {"id": camp.id, "name": camp.name, "query": camp.query}
        suggested = safe_filename(camp.name or camp.query)
        resp: StreamingResponse = await _proxy_pdf_service({
            "campaign": campaign_info,
            "analysis": analysis_payload,
        }, suggested)
        return resp
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report failed: {e}")
# -----------------------------
# Background pipeline (recover → normalize → process)
# -----------------------------
import asyncio

async def _run_all_pipeline(campaign_id: str) -> None:
    # 1) Recover local news and persist as PENDING
    try:
        from .search_local import _recover_campaign_results_task
        await _recover_campaign_results_task(campaign_id)
    except Exception:
        # continue; best-effort
        pass

    # 2) Normalize any NULL statuses to PENDING
    try:
        async with SessionLocal() as db:  # type: AsyncSession
            camp = await db.get(Campaign, campaign_id)
            if not camp:
                return
            rows = (
                await db.execute(
                    select(IngestedItem).where(
                        IngestedItem.campaignId == campaign_id,
                        IngestedItem.status == None,  # noqa: E711
                    )
                )
            ).scalars().all()
            for it in rows:
                it.status = ItemStatus.PENDING
            if rows:
                await db.commit()
    except Exception:
        pass

    # 3) Process pending analyses
    try:
        async with SessionLocal() as db:  # type: AsyncSession
            from .analyses_extra import process_pending as _process_pending
            await _process_pending(campaignId=campaign_id, limit=200, db=db)  # type: ignore
    except Exception:
        pass


@router.post("/campaigns/{campaign_id}/run-all")
async def admin_run_all(
    campaign_id: str,
    background: bool = Query(True, description="Run in background and return immediately"),
    _: dict = Depends(get_current_admin),
    db: AsyncSession = Depends(get_session),
):
    # Validate existence first for quick feedback
    camp = await db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Always background to avoid client/proxy timeouts
    asyncio.create_task(_run_all_pipeline(campaign_id))
    return {"accepted": True, "campaignId": campaign_id, "mode": "async"}
