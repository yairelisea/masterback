
from __future__ import annotations
from typing import List, Dict, Any, Optional
import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from ..db import SessionLocal
from ..models import Campaign, IngestedItem, Analysis, ItemStatus
from .perplexity_service import perplexity_service
from .query_builder import build_basic_query

async def kickoff_campaign_ingest(campaign_id: str) -> None:
    """
    Uses Perplexity to search for news, analyze them, and persist the results
    as IngestedItem and Analysis records.
    """
    async with SessionLocal() as db:  # type: AsyncSession
        campaign = await db.get(Campaign, campaign_id)
        if not campaign:
            return

        q = campaign.query
        campaign_name = campaign.name
        
        # Build a query for Perplexity
        basic_q = build_basic_query(actor=q, campaign_name=campaign_name, city_keywords=campaign.city_keywords)

        # Call Perplexity to get news and analysis
        analyzed_items = await perplexity_service.search_and_analyze(
            query=basic_q, 
            campaign_name=q, # Use actor's name for relevance check
        )

        for item_data in analyzed_items:
            # Create IngestedItem and Analysis in one go using the relationship
            ingested_item = IngestedItem(
                campaignId=campaign.id,
                title=item_data["title"],
                url=item_data["url"],
                publishedAt=item_data.get("publishedAt"),
                status=ItemStatus.PROCESSED, # Mark as processed
                createdAt=datetime.utcnow(),
                analysis=Analysis(
                    campaignId=campaign.id,
                    sentiment=item_data.get("sentiment_score"),
                    tone=item_data.get("sentiment_label"),
                    topics=item_data.get("topics"),
                    summary=item_data.get("summary"),
                )
            )
            db.add(ingested_item)

        try:
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            raise
