from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional, List

from ..db import get_session
from ..models import IngestedItem, Analysis, ItemStatus
from sqlalchemy import select
from ..services.llm import analyze_snippet

router = APIRouter(prefix="/analyses", tags=["analyses"])

@router.post("/process_pending")
async def process_pending(campaignId: Optional[str] = None, limit: int = 200, db: AsyncSession = Depends(get_session)):
    # Procesa solo items con status NULL (compatible con DB antigua sin 'PENDING')
    q = select(IngestedItem).where(IngestedItem.status == None)  # noqa: E711
    if campaignId:
        q = q.where(IngestedItem.campaignId == campaignId)
    rows: List[IngestedItem] = (await db.execute(q)).scalars().all()

    processed = 0
    for it in rows[: max(1, min(limit, 1000)) ]:
        try:
            res = await analyze_snippet(
                title=it.title or "",
                summary="",
                actor="auto",
            )
            # res is a Dict with keys like: summary, sentiment_label, sentiment_score, topics, stance, perception
            a = Analysis(
                campaignId=it.campaignId,
                itemId=it.id,
                sentiment=(res.get("sentiment_score") if isinstance(res, dict) else None),
                tone=(res.get("sentiment_label") if isinstance(res, dict) else None),
                topics=(res.get("topics") if isinstance(res, dict) else None),
                stance=(res.get("stance") if isinstance(res, dict) else None),
                summary=(res.get("summary") if isinstance(res, dict) else None),
                perception=(res.get("perception") if isinstance(res, dict) else None),
            )
            db.add(a)
            try:
                it.status = ItemStatus.PROCESSED
            except Exception:
                # Si el Enum difiere en DB y no acepta PROCESSED, deja NULL
                pass
            processed += 1
        except Exception:
            try:
                it.status = ItemStatus.ERROR
            except Exception:
                pass
    await db.commit()
    return {"processed": processed, "pending_seen": len(rows)}
