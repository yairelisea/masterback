
from __future__ import annotations
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..db import SessionLocal
from ..models import Campaign, IngestedItem, ItemStatus
from .news_fetcher import search_google_news_multi  # conservative entry point
from .search_local import search_local_news

async def _safe_search_google(q: str, lang: str, country: str, since: datetime, size: int) -> List[Dict[str, Any]]:
    try:
        items = await search_google_news_multi(q=q, lang=lang, country=country, since=since, limit=size)
        return items or []
    except Exception:
        return []

async def _safe_search_local(q: str, city_keywords: Optional[list[str]], lang: str, country: str, since: datetime, size: int) -> List[Dict[str, Any]]:
    try:
        items = await search_local_news(q=q, city_keywords=city_keywords, lang=lang, country=country, since=since, limit=size)
        return items or []
    except Exception:
        return []

def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for it in items:
        url = (it.get("url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            out.append(it)
    return out

async def kickoff_campaign_ingest(campaign_id: str) -> None:
    """Run GN + Local search and persist IngestedItem rows for the given campaign."""
    async with SessionLocal() as db:  # type: AsyncSession
        campaign = await db.get(Campaign, campaign_id)
        if not campaign:
            return
        
        q = campaign.query
        lang = campaign.lang or "es-419"
        country = campaign.country or "MX"
        size = campaign.size or 25
        days_back = campaign.days_back or 14
        city_keywords = campaign.city_keywords or None
        since = datetime.utcnow() - timedelta(days=days_back)
        
        all_items: List[Dict[str, Any]] = []
        gn = await _safe_search_google(q, lang, country, since, size)
        all_items.extend(gn)
        ln = await _safe_search_local(q, city_keywords, lang, country, since, max(size, 30))
        all_items.extend(ln)
        
        # normalize to expected keys
        normed = []
        for it in all_items:
            title = (it.get("title") or "").strip()
            url = (it.get("url") or "").strip()
            pub = it.get("publishedAt")
            if not url or not title:
                continue
            normed.append({
                "title": title[:512],
                "url": url,
                "publishedAt": pub
            })
        
        normed = _dedupe(normed)[: max(size, 30)]
        
        for it in normed:
            db.add(IngestedItem(
                campaignId=campaign.id,
                title=it["title"],
                url=it["url"],
                publishedAt=it.get("publishedAt"),
                status=ItemStatus.PENDING
            ))
        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            raise
