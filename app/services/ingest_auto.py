# app/services/ingest_auto.py
from __future__ import annotations
from typing import List, Dict, Any
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from ..db import SessionLocal
from ..models import Campaign, IngestedItem, Analysis, ItemStatus
from .perplexity_service import perplexity_service
from .query_builder import build_basic_query
from datetime import datetime

logger = logging.getLogger(__name__)

async def kickoff_campaign_ingest(campaign_id: str) -> None:
    """
    ✅ INGEST RESILIENTE - NUNCA rompe el backend
    
    Features:
    - Manejo exhaustivo de errores en cada nivel
    - Commits incrementales (cada 5 items)
    - Logging detallado con emojis
    - Guarda partial results si algo falla
    - Cierra sesión DB siempre (finally)
    """
    logger.info(f"🚀 Starting ingestion for campaign: {campaign_id}")
    
    db = None
    try:
        # ✅ Session management explícito
        db = SessionLocal()
        campaign = await db.get(Campaign, campaign_id)
        
        if not campaign:
            logger.error(f"❌ Campaign {campaign_id} not found")
            return

        q = campaign.query
        campaign_name = campaign.name
        
        logger.info(f"📝 Campaign: {campaign_name}, Query: {q}")
        
        # ✅ Build query con manejo de error
        try:
            basic_q = build_basic_query(
                actor=q, 
                campaign_name=campaign_name, 
                city_keywords=campaign.city_keywords
            )
            logger.info(f"🔍 Search query: {basic_q}")
        except Exception as e:
            logger.error(f"❌ Failed to build query: {e}")
            basic_q = q  # Fallback a query original

        # ✅ Perplexity search con retry y timeout
        analyzed_items = []
        try:
            analyzed_items = await perplexity_service.search_and_analyze(
                query=basic_q, 
                campaign_name=q,
                city_keywords=campaign.city_keywords,
                min_relevance_score=40.0,
            )
            logger.info(f"✅ Found {len(analyzed_items)} items from Perplexity")
            
        except Exception as e:
            logger.error(f"❌ Perplexity search failed: {e}", exc_info=True)
            # ✅ NO romper aquí - continuar con 0 items
            analyzed_items = []

        # ✅ Si no hay items, terminar limpiamente
        if not analyzed_items:
            logger.warning(f"⚠️ No items found for campaign {campaign_id}")
            await db.close()
            return

        # ✅ Persistir items UNO POR UNO (partial success)
        saved_count = 0
        failed_count = 0
        
        for idx, item_data in enumerate(analyzed_items):
            try:
                # Validación básica
                if not item_data.get("title") or not item_data.get("url"):
                    logger.warning(f"⚠️ Item {idx} missing title/url, skipping")
                    failed_count += 1
                    continue

                # ✅ Dedupe por URL (sin usar columnas inexistentes)
                from sqlalchemy import text
                existing = await db.execute(
                    text('SELECT 1 FROM ingested_items WHERE "campaignId" = :cid AND url = :url LIMIT 1'),
                    {"cid": campaign.id, "url": item_data["url"]}
                )
                if existing.first():
                    logger.debug(f"⏭️ Item {idx} already exists: {item_data['url']}")
                    continue

                # Crear item + analysis
                ingested_item = IngestedItem(
                    campaignId=campaign.id,
                    title=item_data["title"][:500],  # ✅ Truncar para evitar overflow
                    url=item_data["url"][:2000],
                    publishedAt=item_data.get("publishedAt"),
                    status=ItemStatus.PROCESSED,
                    createdAt=datetime.utcnow(),
                )
                
                # ✅ Analysis opcional (puede no existir)
                if any(k in item_data for k in ["sentiment_score", "summary", "topics"]):
                    ingested_item.analysis = Analysis(
                        campaignId=campaign.id,
                        sentiment=item_data.get("sentiment_score"),
                        tone=item_data.get("sentiment_label"),
                        topics=item_data.get("topics", [])[:10],  # ✅ Limitar topics
                        summary=item_data.get("summary", "")[:2000],  # ✅ Truncar
                    )
                
                db.add(ingested_item)
                saved_count += 1
                
                # ✅ Commit cada 5 items (batch pequeño para no perder mucho si falla)
                if saved_count % 5 == 0:
                    try:
                        await db.commit()
                        logger.info(f"💾 Saved batch: {saved_count}/{len(analyzed_items)}")
                    except SQLAlchemyError as e:
                        logger.error(f"❌ Batch commit failed: {e}")
                        await db.rollback()
                        failed_count += 5
                        saved_count -= 5
                        
            except Exception as e:
                logger.error(f"❌ Failed to save item {idx}: {e}")
                failed_count += 1
                continue  # ✅ Continuar con siguiente item

        # ✅ Commit final
        try:
            await db.commit()
            logger.info(f"✅ Final commit successful")
        except SQLAlchemyError as e:
            logger.error(f"❌ Final commit failed: {e}")
            await db.rollback()

        logger.info(f"✅ Ingestion complete for {campaign_id}: {saved_count} saved, {failed_count} failed")
        
    except Exception as e:
        # ✅ Catch-all final - NUNCA romper
        logger.error(f"❌ Critical error in ingestion for {campaign_id}: {e}", exc_info=True)
        
    finally:
        # ✅ SIEMPRE cerrar sesión
        if db:
            try:
                await db.close()
            except Exception:
                pass