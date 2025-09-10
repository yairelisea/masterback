from __future__ import annotations
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from ..db import get_session
from ..models import Campaign
from ..deps import get_current_user

router = APIRouter(prefix="/admin", tags=["admin-tools"])

@router.post("/campaigns/{campaign_id}/recover")
async def admin_recover_campaign(
    campaign_id: str,
    current_user: dict = Depends(get_current_user),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_session),
):
    if not current_user or current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    camp = await db.get(Campaign, campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail="Campaign not found")

    token = authorization.split(" ", 1)[1].strip() if (authorization and authorization.lower().startswith("bearer ")) else ""
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")

    try:
        from ..services.pipeline import run_gn_local_analyses
        result = await run_gn_local_analyses(token, campaign_id)
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline error: {e}")