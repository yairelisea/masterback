# app/services/news_sentiment.py
from __future__ import annotations
import os, math, asyncio
from typing import List, Dict, Any
import httpx
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..models import Campaign

GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")  # Programmable Search Engine (cx)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")  # API key

_analyzer = SentimentIntensityAnalyzer()

async def _google_cse_search(query: str, *, num: int = 10) -> List[Dict[str, Any]]:
    """Call Google Programmable Search restricted to news.google.com.
    Returns list of items with keys: title, link, snippet.
    """
    if not (GOOGLE_CSE_ID and GOOGLE_API_KEY):
        return []
    # Google CSE num max 10 per request; we keep it simple (1 page)
    params = {
        "q": query,
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "num": min(num, 10),
        "siteSearch": "news.google.com",
        "siteSearchFilter": "i",  # include only this site
        "hl": "es",
    }
    url = "https://www.googleapis.com/customsearch/v1"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:
        return []
    items = []
    for it in data.get("items", []):
        items.append({
            "title": it.get("title") or "",
            "link": it.get("link") or "",
            "snippet": it.get("snippet") or "",
        })
    return items

async def run_initial_news_sentiment(campaign_id: str, db_factory) -> None:
    """Background task: fetch news for campaign.name, compute avg sentiment, store JSON.
    db_factory: a callable returning an AsyncSession (e.g., SessionLocal)
    """
    try:
        async with db_factory() as db:  # type: AsyncSession
            campaign = await db.get(Campaign, campaign_id)
            if not campaign:
                return
            query = campaign.name
            articles = await _google_cse_search(query, num=6)
            if not articles:
                # store empty structure so client knows it intent was executed
                campaign.news_analysis = {"avg_sentiment": None, "articles": []}
                await db.commit()
                return
            scores = []
            simplified: List[Dict[str, Any]] = []
            for a in articles[:6]:  # analyze up to 6 for better average
                title = a.get("title", "")
                if title:
                    vs = _analyzer.polarity_scores(title)
                    scores.append(vs.get("compound", 0.0))
                simplified.append({
                    "title": a.get("title"),
                    "link": a.get("link"),
                    "snippet": a.get("snippet"),
                })
            avg = round(sum(scores)/len(scores), 4) if scores else 0.0
            campaign.news_analysis = {
                "avg_sentiment": avg,
                "articles": simplified[:3],  # only first 3 to persist
                "total_scored": len(scores),
            }
            await db.commit()
    except Exception:
        # swallow to avoid breaking main flow
        return
