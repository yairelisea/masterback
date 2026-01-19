# app/services/ingestion_service.py
"""
Servicio de Ingesta Dirigida para BBX Monitor.

Este servicio implementa el flujo completo de:
1. Consultar MonitoringSources y agrupar URLs
2. Ejecutar Actor de Apify (alien_force/facebook-scraper-pro)
3. Vaciar resultados en RawScrapeData (sin duplicados)
4. Disparar análisis automático de nuevos datos
"""
from __future__ import annotations

import os
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import select, and_, or_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

# Apify client
try:
    from apify_client import ApifyClient
    APIFY_AVAILABLE = True
except ImportError:
    ApifyClient = None
    APIFY_AVAILABLE = False

logger = logging.getLogger(__name__)

# Configuración
APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN")

# Actor de Facebook recomendado
FACEBOOK_ACTOR = "apify/facebook-posts-scraper"

# Configuración por defecto
DEFAULT_MAX_POSTS = 100
DEFAULT_DAYS_BACK = 7


class IngestionService:
    """
    Servicio principal de ingesta de datos desde redes sociales.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._client = None

    @property
    def client(self) -> ApifyClient:
        """Obtiene el cliente de Apify (lazy initialization)"""
        if self._client is None:
            if not APIFY_AVAILABLE:
                raise ValueError("apify-client no está instalado")
            if not APIFY_API_TOKEN:
                raise ValueError("APIFY_API_TOKEN no está configurado")
            self._client = ApifyClient(APIFY_API_TOKEN)
        return self._client

    # =========================================================================
    # PASO 1: Consultar MonitoringSources y agrupar URLs
    # =========================================================================
    async def get_active_sources(
        self,
        campaign_id: Optional[str] = None,
        platform: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Obtiene las fuentes de monitoreo activas.

        Args:
            campaign_id: Si se especifica, solo fuentes de esa campaña
            platform: Si se especifica, solo fuentes de esa plataforma

        Returns:
            Lista de fuentes con url, platform_type, campaign_id, etc.
        """
        from ..models import MonitoringSource, MonitoringStatus

        query = select(MonitoringSource).where(
            MonitoringSource.status == MonitoringStatus.ACTIVE
        )

        if campaign_id:
            query = query.where(MonitoringSource.campaignId == campaign_id)

        if platform:
            query = query.where(MonitoringSource.platform == platform)

        result = await self.db.execute(query)
        sources = result.scalars().all()

        return [
            {
                "id": s.id,
                "url": s.url,
                "platform": s.platform.value if s.platform else "facebook",
                "campaign_id": s.campaignId,
                "name": s.name,
                "last_run_at": s.lastRunAt,
            }
            for s in sources
        ]

    def group_sources_by_platform(
        self,
        sources: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Agrupa las fuentes por plataforma para procesamiento eficiente.
        """
        grouped = {}
        for source in sources:
            platform = source.get("platform", "facebook")
            if platform not in grouped:
                grouped[platform] = []
            grouped[platform].append(source)
        return grouped

    # =========================================================================
    # PASO 2: Ejecutar Actor de Apify
    # =========================================================================
    async def run_facebook_scraper(
        self,
        urls: List[str],
        max_posts: int = DEFAULT_MAX_POSTS,
        days_back: int = DEFAULT_DAYS_BACK
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Ejecuta el Actor alien_force/facebook-scraper-pro en Apify.

        Args:
            urls: Lista de URLs de páginas/grupos de Facebook
            max_posts: Máximo de posts por URL
            days_back: Días hacia atrás para buscar

        Returns:
            Tuple de (lista de posts, metadata de la ejecución)
        """
        from datetime import timedelta
        since_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        # Configuración del Actor apify/facebook-posts-scraper
        run_input = {
            "startUrls": [{"url": u} for u in urls],
            "maxPosts": max_posts,
            "maxPostDate": since_date,
            "maxComments": 0,
            "maxReviews": 0,
            "resultsLimit": max_posts * len(urls),
        }

        print(f"🔵 Ejecutando {FACEBOOK_ACTOR} con {len(urls)} URLs...")
        print(f"   Max posts: {max_posts}, Días: {days_back}")

        try:
            # Ejecutar el Actor en thread pool para no bloquear
            loop = asyncio.get_event_loop()
            run = await loop.run_in_executor(
                None,
                lambda: self.client.actor(FACEBOOK_ACTOR).call(
                    run_input=run_input,
                    timeout_secs=300  # 5 minutos máximo
                )
            )

            # Obtener resultados del dataset
            items = list(self.client.dataset(run["defaultDatasetId"]).iterate_items())

            metadata = {
                "run_id": run.get("id"),
                "status": run.get("status"),
                "started_at": run.get("startedAt"),
                "finished_at": run.get("finishedAt"),
                "items_count": len(items),
                "compute_units": run.get("usageTotalUsd"),
            }

            print(f"   ✅ Scraping completado: {len(items)} posts encontrados")
            return items, metadata

        except Exception as e:
            print(f"   ❌ Error en scraping: {e}")
            raise

    # =========================================================================
    # PASO 3: Vaciar resultados en RawScrapeData (sin duplicados)
    # =========================================================================
    async def store_raw_data(
        self,
        items: List[Dict[str, Any]],
        source_id: str,
        platform: str = "facebook"
    ) -> Dict[str, int]:
        """
        Almacena los datos crudos en RawScrapeData.
        Usa UPSERT para evitar duplicados (postUrl como clave única).

        Args:
            items: Lista de posts de Apify
            source_id: ID de la MonitoringSource
            platform: Plataforma de origen

        Returns:
            Estadísticas: {"inserted": N, "updated": M, "skipped": K}
        """
        from ..models import RawScrapeData

        stats = {"inserted": 0, "updated": 0, "skipped": 0}

        for item in items:
            # Extraer datos según la estructura del Actor
            post_url = item.get("url") or item.get("postUrl") or item.get("link")

            if not post_url:
                stats["skipped"] += 1
                continue

            # Preparar datos para insertar
            raw_data = {
                "sourceId": source_id,
                "postUrl": post_url,
                "rawText": item.get("text") or item.get("message") or item.get("content"),
                "postDate": self._parse_date(item.get("time") or item.get("timestamp")),
                "postAuthor": item.get("user", {}).get("name") if isinstance(item.get("user"), dict) else item.get("author"),
                "metadataJson": item,  # Guardamos todo el JSON original
                "likes": item.get("likes") or item.get("reactions") or 0,
                "shares": item.get("shares") or 0,
                "comments": item.get("commentsCount") or item.get("comments") or 0,
                "views": item.get("views") or 0,
                "platform": platform,
                "isProcessed": False,
                "createdAt": datetime.now(timezone.utc),
            }

            try:
                # Intentar INSERT, si falla por duplicado, actualizamos
                stmt = insert(RawScrapeData).values(**raw_data)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["postUrl"],
                    set_={
                        "rawText": stmt.excluded.rawText,
                        "likes": stmt.excluded.likes,
                        "shares": stmt.excluded.shares,
                        "comments": stmt.excluded.comments,
                        "views": stmt.excluded.views,
                        "metadataJson": stmt.excluded.metadataJson,
                    }
                )
                await self.db.execute(stmt)
                stats["inserted"] += 1

            except Exception as e:
                print(f"   ⚠️ Error insertando post {post_url[:50]}: {e}")
                stats["skipped"] += 1

        await self.db.commit()
        print(f"   📊 Almacenamiento: {stats['inserted']} nuevos, {stats['skipped']} omitidos")
        return stats

    def _parse_date(self, date_str: Any) -> Optional[datetime]:
        """Parsea una fecha de Apify a datetime"""
        if date_str is None:
            return None

        if isinstance(date_str, datetime):
            return date_str

        if isinstance(date_str, str):
            try:
                # Intentar varios formatos
                for fmt in [
                    "%Y-%m-%dT%H:%M:%S.%fZ",
                    "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d",
                ]:
                    try:
                        return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
            except Exception:
                pass

        return None

    # =========================================================================
    # FLUJO COMPLETO DE INGESTA
    # =========================================================================
    async def run_full_ingestion(
        self,
        campaign_id: Optional[str] = None,
        max_posts: int = DEFAULT_MAX_POSTS,
        days_back: int = DEFAULT_DAYS_BACK
    ) -> Dict[str, Any]:
        """
        Ejecuta el flujo completo de ingesta:
        1. Obtener fuentes activas
        2. Agrupar por plataforma
        3. Ejecutar scrapers
        4. Almacenar en RawScrapeData

        Args:
            campaign_id: Si se especifica, solo procesa esa campaña
            max_posts: Máximo posts por fuente
            days_back: Días hacia atrás

        Returns:
            Resumen de la ingesta
        """
        from ..models import MonitoringSource

        print(f"\n{'='*60}")
        print(f"🚀 INICIANDO INGESTA DIRIGIDA")
        print(f"   Campaña: {campaign_id or 'TODAS'}")
        print(f"   Max posts: {max_posts}, Días: {days_back}")
        print(f"{'='*60}\n")

        start_time = datetime.now(timezone.utc)
        results = {
            "started_at": start_time.isoformat(),
            "campaign_id": campaign_id,
            "sources_processed": 0,
            "total_posts_found": 0,
            "total_posts_stored": 0,
            "errors": [],
            "by_platform": {}
        }

        # 1. Obtener fuentes activas
        sources = await self.get_active_sources(campaign_id=campaign_id)
        if not sources:
            print("⚠️ No hay fuentes de monitoreo activas")
            results["errors"].append("No hay fuentes activas")
            return results

        print(f"📋 Fuentes activas encontradas: {len(sources)}")

        # 2. Agrupar por plataforma
        grouped = self.group_sources_by_platform(sources)

        # 3. Procesar cada plataforma
        for platform, platform_sources in grouped.items():
            print(f"\n🔹 Procesando {platform.upper()}: {len(platform_sources)} fuentes")

            platform_result = {
                "sources": len(platform_sources),
                "posts_found": 0,
                "posts_stored": 0,
            }

            try:
                if platform == "facebook":
                    # Extraer URLs
                    urls = [s["url"] for s in platform_sources]

                    # Ejecutar scraper
                    items, metadata = await self.run_facebook_scraper(
                        urls=urls,
                        max_posts=max_posts,
                        days_back=days_back
                    )

                    platform_result["posts_found"] = len(items)

                    # Almacenar resultados (asociar con la primera fuente para simplificar)
                    # En producción, deberías mapear cada post a su fuente correspondiente
                    for source in platform_sources:
                        # Filtrar items por URL de la fuente
                        source_items = [
                            item for item in items
                            if source["url"] in (item.get("url") or item.get("pageUrl") or "")
                        ]

                        if source_items:
                            stats = await self.store_raw_data(
                                items=source_items,
                                source_id=source["id"],
                                platform=platform
                            )
                            platform_result["posts_stored"] += stats["inserted"]

                            # Actualizar lastRunAt de la fuente
                            await self.db.execute(
                                select(MonitoringSource).where(
                                    MonitoringSource.id == source["id"]
                                )
                            )

                else:
                    print(f"   ⚠️ Plataforma {platform} no implementada aún")

            except Exception as e:
                error_msg = f"Error en {platform}: {str(e)}"
                print(f"   ❌ {error_msg}")
                results["errors"].append(error_msg)
                platform_result["error"] = str(e)

            results["by_platform"][platform] = platform_result
            results["sources_processed"] += platform_result["sources"]
            results["total_posts_found"] += platform_result["posts_found"]
            results["total_posts_stored"] += platform_result["posts_stored"]

        # Resumen final
        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        results["elapsed_seconds"] = round(elapsed, 2)
        results["finished_at"] = datetime.now(timezone.utc).isoformat()

        print(f"\n{'='*60}")
        print(f"✅ INGESTA COMPLETADA")
        print(f"   Fuentes procesadas: {results['sources_processed']}")
        print(f"   Posts encontrados: {results['total_posts_found']}")
        print(f"   Posts almacenados: {results['total_posts_stored']}")
        print(f"   Tiempo: {results['elapsed_seconds']}s")
        print(f"{'='*60}\n")

        return results


# =========================================================================
# FUNCIÓN HELPER PARA USAR EL SERVICIO
# =========================================================================
async def run_ingestion(
    db: AsyncSession,
    campaign_id: Optional[str] = None,
    max_posts: int = DEFAULT_MAX_POSTS,
    days_back: int = DEFAULT_DAYS_BACK
) -> Dict[str, Any]:
    """
    Helper function para ejecutar la ingesta.
    """
    service = IngestionService(db)
    return await service.run_full_ingestion(
        campaign_id=campaign_id,
        max_posts=max_posts,
        days_back=days_back
    )
