from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List

from ..db import get_session
from ..models import IngestedItem, Analysis
from ..schemas import ItemStatusEnum
from ..services.llm import analyze_snippet

router = APIRouter(prefix="/analyses", tags=["analyses"])

@router.post("/process_pending")
async def process_pending(campaignId: Optional[str] = None, limit: int = 200, db: AsyncSession = Depends(get_session)):
    q = select(IngestedItem).where(IngestedItem.status == ItemStatusEnum.PENDING)
    if campaignId:
        q = q.where(IngestedItem.campaignId == campaignId)
    rows: List[IngestedItem] = (await db.execute(q)).scalars().all()

    processed = 0
    for it in rows[: max(1, min(limit, 1000)) ]:
        try:
            res = await analyze_snippet(
                title=it.title or "",
                summary=it.snippet or "",
                actor="auto",
                language="es",
            )
            a = Analysis(
                campaignId=it.campaignId,
                itemId=it.id,
                sentiment=res.sentiment,
                tone=res.tone,
                topics=res.topics,
                summary=(res.verdict or (res.key_points[0] if res.key_points else None)),
                perception=res.perception,
            )
            db.add(a)
            it.status = ItemStatusEnum.PROCESSED
            processed += 1
        except Exception:
            it.status = ItemStatusEnum.ERROR
    await db.commit()
    return {"processed": processed, "pending_seen": len(rows)}