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

async def kickoff_campaign_ingest(
    campaign_id: str,
    priorizar_medios_locales: bool = True
) -> None:
    """
    Ejecuta búsqueda y análisis de noticias usando Perplexity con priorización de medios locales.
    
    Args:
        campaign_id: ID de la campaña
        priorizar_medios_locales: Si True, da boost a medios locales de Tampico
    
    Características:
    - ✅ Búsqueda iterativa (3 intentos con umbrales progresivos)
    - ✅ Priorización de medios locales (Sol de Tampico, Milenio, etc.)
    - ✅ Boost de scoring para medios locales
    - ✅ Sin parámetro city_keywords (CORREGIDO)
    """
    async with SessionLocal() as db:  # type: AsyncSession
        campaign = await db.get(Campaign, campaign_id)
        if not campaign:
            print(f"❌ Campaña {campaign_id} no encontrada")
            return

        q = campaign.query
        campaign_name = campaign.name
        
        print(f"\n{'='*60}")
        print(f"🚀 INICIANDO INGESTIÓN DE CAMPAÑA")
        print(f"   ID: {campaign_id}")
        print(f"   Nombre: {campaign_name}")
        print(f"   Query: {q}")
        print(f"   Medios locales: {'✅ PRIORIZADOS' if priorizar_medios_locales else '❌ No'}")
        print(f"{'='*60}\n")
        
        # ✅ CORRECCIÓN: Solo pasamos query y campaign_name (SIN city_keywords)
        basic_q = build_basic_query(
            actor=q, 
            campaign_name=campaign_name
        )

        # Llamar a Perplexity con priorización de medios locales
        analyzed_items = await perplexity_service.search_and_analyze(
            query=basic_q, 
            campaign_name=campaign_name,
            priorizar_medios_locales=priorizar_medios_locales
        )

        print(f"\n📊 Resultados del análisis: {len(analyzed_items)} artículos")
        
        if priorizar_medios_locales:
            locales = sum(1 for item in analyzed_items if item.get("es_medio_local", False))
            print(f"   🏠 Medios locales: {locales}/{len(analyzed_items)}")

        # Persistir resultados en la base de datos
        items_creados = 0
        items_fallidos = 0
        
        for item_data in analyzed_items:
            try:
                # Crear IngestedItem con Analysis relacionado
                ingested_item = IngestedItem(
                    campaignId=campaign.id,
                    title=item_data["title"],
                    url=item_data["url"],
                    publishedAt=item_data.get("publishedAt"),
                    status=ItemStatus.PROCESSED,
                    createdAt=datetime.utcnow(),
                    analysis=Analysis(
                        campaignId=campaign.id,
                        sentiment=item_data.get("sentiment_score", 0.0),
                        tone=item_data.get("sentiment_label", "Neutral"),
                        topics=item_data.get("topics", []),
                        summary=item_data.get("summary", ""),
                        # Metadatos adicionales
                        metadata={
                            "key_points": item_data.get("key_points", []),
                            "relevance_score": item_data.get("relevance_score", 0.0),
                            "es_medio_local": item_data.get("es_medio_local", False)
                        }
                    )
                )
                db.add(ingested_item)
                items_creados += 1
                
                # Logging detallado
                medio_emoji = "🏠" if item_data.get("es_medio_local") else "🌐"
                print(f"{medio_emoji} [{items_creados}] {item_data['title'][:80]}...")
                print(f"    Sentimiento: {item_data.get('sentiment_label')} ({item_data.get('sentiment_score', 0):.2f})")
                print(f"    URL: {item_data['url']}")
                
            except Exception as e:
                items_fallidos += 1
                print(f"❌ Error al persistir item: {e}")
                print(f"   Título: {item_data.get('title', 'N/A')}")
                continue

        # Commit de todos los cambios
        try:
            await db.commit()
            print(f"\n{'='*60}")
            print(f"✅ INGESTIÓN COMPLETADA")
            print(f"   Items creados: {items_creados}")
            print(f"   Items fallidos: {items_fallidos}")
            print(f"   Total procesados: {items_creados + items_fallidos}")
            print(f"{'='*60}\n")
            
        except SQLAlchemyError as e:
            await db.rollback()
            print(f"❌ Error al hacer commit: {e}")
            raise


async def kickoff_campaign_ingest_batch(
    campaign_ids: List[str],
    priorizar_medios_locales: bool = True
) -> Dict[str, Any]:
    """
    Ejecuta ingestión para múltiples campañas en batch.
    
    Returns:
        Dict con estadísticas de la ejecución batch
    """
    resultados = {
        "total_campañas": len(campaign_ids),
        "exitosas": 0,
        "fallidas": 0,
        "detalles": []
    }
    
    print(f"\n🔄 INICIO BATCH: {len(campaign_ids)} campañas")
    
    for i, campaign_id in enumerate(campaign_ids, 1):
        print(f"\n--- Campaña {i}/{len(campaign_ids)} ---")
        try:
            await kickoff_campaign_ingest(
                campaign_id=campaign_id,
                priorizar_medios_locales=priorizar_medios_locales
            )
            resultados["exitosas"] += 1
            resultados["detalles"].append({
                "campaign_id": campaign_id,
                "status": "exitosa"
            })
        except Exception as e:
            resultados["fallidas"] += 1
            resultados["detalles"].append({
                "campaign_id": campaign_id,
                "status": "fallida",
                "error": str(e)
            })
            print(f"❌ Error en campaña {campaign_id}: {e}")
    
    print(f"\n{'='*60}")
    print(f"📊 RESUMEN BATCH")
    print(f"   Total: {resultados['total_campañas']}")
    print(f"   ✅ Exitosas: {resultados['exitosas']}")
    print(f"   ❌ Fallidas: {resultados['fallidas']}")
    print(f"{'='*60}\n")
    
    return resultados