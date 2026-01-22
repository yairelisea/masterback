# app/services/analysis_engine.py
"""
Motor de Filtrado y Análisis SOCMINT para BBX Monitor.

Este servicio implementa:
- Momento A: Análisis de nuevos scrapes (cuando entran datos a RawScrapeData)
- Momento B: Retro-análisis (backfill cuando se crea una nueva campaña)
- Integración con IA para análisis SOCMINT
"""
from __future__ import annotations

import os
import re
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import select, and_, or_, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

logger = logging.getLogger(__name__)

# Configuración de IA
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Prompt SOCMINT para análisis político
SOCMINT_SYSTEM_PROMPT = """Actúa como analista SOCMINT político especializado en México.
Analiza el siguiente texto de redes sociales y devuelve EXCLUSIVAMENTE un JSON válido con:

{
    "sentiment": <número entre -1 y 1>,
    "category": "<Seguridad|Economía|Ataque|Gestión|Corrupción|Otros>",
    "risk_level": "<Bajo|Medio|Alto|Crítico>",
    "summary": "<resumen máximo 15 palabras>",
    "intent": "<Informar|Movilizar|Difamar>"
}

IMPORTANTE:
- sentiment: -1 es muy negativo, 0 es neutral, 1 es muy positivo
- category: clasifica el tema principal del contenido
- risk_level: evalúa el potencial de daño reputacional
- summary: resumen conciso del contenido
- intent: la intención aparente del autor

Responde SOLO con el JSON, sin explicaciones adicionales."""


class AnalysisEngine:
    """
    Motor de análisis que procesa datos crudos y los enriquece con IA.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # =========================================================================
    # MOMENTO A: Análisis de nuevos scrapes
    # =========================================================================
    async def process_new_scrapes(
        self,
        limit: int = 100,
        campaign_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Procesa datos nuevos en RawScrapeData que aún no han sido analizados.

        Este método se ejecuta después de cada ingesta o como job periódico.

        Args:
            limit: Máximo de registros a procesar
            campaign_id: Si se especifica, solo procesa para esa campaña

        Returns:
            Estadísticas del procesamiento
        """
        from ..models import RawScrapeData, Campaign, CampaignAnalysis

        print(f"\n{'='*60}")
        print(f"🔄 MOMENTO A: Procesando nuevos scrapes")
        print(f"{'='*60}")

        stats = {
            "processed": 0,
            "matched": 0,
            "analyzed": 0,
            "errors": 0,
            "by_campaign": {}
        }

        # Usar no_autoflush para evitar deadlocks (es sync, no async)
        with self.db.no_autoflush:
            # 1. Obtener IDs de datos no procesados (solo IDs para evitar locks)
            query = select(RawScrapeData.id).where(
                RawScrapeData.isProcessed == False
            ).order_by(RawScrapeData.createdAt.desc()).limit(limit)

            result = await self.db.execute(query)
            raw_ids = [row[0] for row in result.fetchall()]

            if not raw_ids:
                print("   ℹ️ No hay datos nuevos para procesar")
                return stats

            print(f"   📊 Datos pendientes: {len(raw_ids)}")

            # 2. Obtener todas las campañas activas (o solo la especificada)
            campaigns_query = select(Campaign)
            if campaign_id:
                campaigns_query = campaigns_query.where(Campaign.id == campaign_id)

            campaigns_result = await self.db.execute(campaigns_query)
            campaigns = campaigns_result.scalars().all()

            print(f"   📋 Campañas activas: {len(campaigns)}")

            # 3. Procesar cada item individualmente para evitar deadlocks
            for raw_id in raw_ids:
                try:
                    # Obtener el item fresco
                    raw_item = await self.db.get(RawScrapeData, raw_id)
                    if not raw_item or raw_item.isProcessed:
                        continue

                    stats["processed"] += 1
                    text_content = raw_item.rawText or ""

                    for campaign in campaigns:
                        # Obtener keywords de la campaña
                        keywords = self._get_campaign_keywords(campaign)

                        # Buscar coincidencias
                        matched_keywords = self._find_keyword_matches(text_content, keywords)

                        if matched_keywords:
                            stats["matched"] += 1

                            # Verificar si ya existe análisis para este par (raw_id, campaign_id)
                            existing = await self.db.execute(
                                select(CampaignAnalysis.id).where(
                                    and_(
                                        CampaignAnalysis.rawId == raw_item.id,
                                        CampaignAnalysis.campaignId == campaign.id
                                    )
                                )
                            )

                            if existing.scalar_one_or_none():
                                # Ya existe, saltar
                                continue

                            # Enviar a análisis de IA
                            try:
                                analysis_result = await self._analyze_with_ai(text_content)

                                # Guardar resultado
                                new_analysis = CampaignAnalysis(
                                    rawId=raw_item.id,
                                    campaignId=campaign.id,
                                    sentimentScore=analysis_result.get("sentiment"),
                                    category=self._map_category(analysis_result.get("category")),
                                    riskLevel=self._map_risk_level(analysis_result.get("risk_level")),
                                    summary=analysis_result.get("summary"),
                                    intent=self._map_intent(analysis_result.get("intent")),
                                    matchedKeywords=matched_keywords,
                                    rawAIResponse=analysis_result,
                                    analysisModel="perplexity",
                                    isAnalyzed=True,
                                    analyzedAt=datetime.now(timezone.utc)
                                )

                                self.db.add(new_analysis)
                                stats["analyzed"] += 1

                                # Tracking por campaña
                                if campaign.id not in stats["by_campaign"]:
                                    stats["by_campaign"][campaign.id] = {"name": campaign.name, "count": 0}
                                stats["by_campaign"][campaign.id]["count"] += 1

                            except Exception as e:
                                print(f"   ⚠️ Error analizando: {e}")
                                stats["errors"] += 1

                    # Marcar como procesado usando UPDATE directo para evitar conflictos
                    await self.db.execute(
                        text("UPDATE raw_scrape_data SET \"isProcessed\" = true WHERE id = :id"),
                        {"id": raw_id}
                    )

                    # Commit después de cada item para liberar locks
                    await self.db.commit()

                except Exception as e:
                    print(f"   ⚠️ Error procesando item {raw_id}: {e}")
                    stats["errors"] += 1
                    await self.db.rollback()

        print(f"\n   ✅ Procesamiento completado:")
        print(f"      - Procesados: {stats['processed']}")
        print(f"      - Con coincidencias: {stats['matched']}")
        print(f"      - Analizados con IA: {stats['analyzed']}")
        print(f"      - Errores: {stats['errors']}")

        # Normalizar claves para el endpoint
        stats["posts_analyzed"] = stats["analyzed"]
        stats["posts_relevant"] = stats["matched"]

        return stats

    # =========================================================================
    # MOMENTO B: Retro-análisis (Backfill para nueva campaña)
    # =========================================================================
    async def run_backfill_for_campaign(
        self,
        campaign_id: str,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Ejecuta retro-análisis cuando se crea una nueva campaña.

        Busca en TODO el histórico de RawScrapeData coincidencias con
        las palabras clave del nuevo candidato.

        Args:
            campaign_id: ID de la nueva campaña
            limit: Máximo de registros a procesar

        Returns:
            Estadísticas del backfill
        """
        from ..models import RawScrapeData, Campaign, CampaignAnalysis

        print(f"\n{'='*60}")
        print(f"📚 MOMENTO B: Retro-análisis para campaña {campaign_id}")
        print(f"{'='*60}")

        stats = {
            "campaign_id": campaign_id,
            "historical_searched": 0,
            "matches_found": 0,
            "already_analyzed": 0,
            "new_analyses": 0,
            "errors": 0,
        }

        # 1. Obtener la campaña
        campaign_result = await self.db.execute(
            select(Campaign).where(Campaign.id == campaign_id)
        )
        campaign = campaign_result.scalar_one_or_none()

        if not campaign:
            print(f"   ❌ Campaña no encontrada: {campaign_id}")
            stats["error"] = "Campaña no encontrada"
            return stats

        print(f"   📋 Campaña: {campaign.name}")
        print(f"   🔍 Query: {campaign.query}")

        # 2. Obtener keywords
        keywords = self._get_campaign_keywords(campaign)
        print(f"   🔑 Keywords: {keywords}")

        # 3. Búsqueda en histórico usando full-text search de PostgreSQL
        # Esto es MUCHO más eficiente que cargar todos los registros
        search_terms = " | ".join(keywords)  # OR para tsquery

        query = text("""
            SELECT id, "rawText", "postUrl", "postDate", "postAuthor"
            FROM raw_scrape_data
            WHERE to_tsvector('spanish', COALESCE("rawText", '')) @@ to_tsquery('spanish', :search_terms)
            ORDER BY "createdAt" DESC
            LIMIT :limit
        """)

        result = await self.db.execute(query, {"search_terms": search_terms, "limit": limit})
        matches = result.fetchall()

        stats["historical_searched"] = limit  # Aproximado
        stats["matches_found"] = len(matches)

        print(f"   📊 Coincidencias encontradas: {len(matches)}")

        # 4. Procesar cada coincidencia
        for match in matches:
            raw_id = match[0]
            raw_text = match[1]

            # Verificar si ya existe análisis
            existing = await self.db.execute(
                select(CampaignAnalysis).where(
                    and_(
                        CampaignAnalysis.rawId == raw_id,
                        CampaignAnalysis.campaignId == campaign_id
                    )
                )
            )

            if existing.scalar_one_or_none():
                stats["already_analyzed"] += 1
                continue

            # Encontrar keywords específicos que matchearon
            matched_keywords = self._find_keyword_matches(raw_text or "", keywords)

            # Analizar con IA
            try:
                analysis_result = await self._analyze_with_ai(raw_text or "")

                new_analysis = CampaignAnalysis(
                    rawId=raw_id,
                    campaignId=campaign_id,
                    sentimentScore=analysis_result.get("sentiment"),
                    category=self._map_category(analysis_result.get("category")),
                    riskLevel=self._map_risk_level(analysis_result.get("risk_level")),
                    summary=analysis_result.get("summary"),
                    intent=self._map_intent(analysis_result.get("intent")),
                    matchedKeywords=matched_keywords,
                    rawAIResponse=analysis_result,
                    analysisModel="perplexity",
                    isAnalyzed=True,
                    analyzedAt=datetime.now(timezone.utc)
                )

                self.db.add(new_analysis)
                stats["new_analyses"] += 1

            except Exception as e:
                print(f"   ⚠️ Error en backfill: {e}")
                stats["errors"] += 1

        await self.db.commit()

        print(f"\n   ✅ Backfill completado:")
        print(f"      - Coincidencias: {stats['matches_found']}")
        print(f"      - Ya analizados: {stats['already_analyzed']}")
        print(f"      - Nuevos análisis: {stats['new_analyses']}")
        print(f"      - Errores: {stats['errors']}")

        return stats

    # =========================================================================
    # INTEGRACIÓN CON IA
    # =========================================================================
    async def _analyze_with_ai(self, text: str) -> Dict[str, Any]:
        """
        Envía texto a la IA para análisis SOCMINT.

        Usa Perplexity como primera opción, OpenAI como fallback.
        """
        if not text or len(text.strip()) < 10:
            return {
                "sentiment": 0,
                "category": "Otros",
                "risk_level": "Bajo",
                "summary": "Contenido insuficiente para analizar",
                "intent": "Informar"
            }

        # Limitar texto a 2000 caracteres para optimizar tokens
        text = text[:2000]

        try:
            if PERPLEXITY_API_KEY:
                return await self._call_perplexity(text)
            elif OPENAI_API_KEY:
                return await self._call_openai(text)
            else:
                # Fallback: análisis básico sin IA
                return self._basic_analysis(text)

        except Exception as e:
            print(f"   ⚠️ Error en IA, usando análisis básico: {e}")
            return self._basic_analysis(text)

    async def _call_perplexity(self, text: str) -> Dict[str, Any]:
        """Llama a la API de Perplexity para análisis"""
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "sonar",
                    "messages": [
                        {"role": "system", "content": SOCMINT_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Analiza este texto:\n\n{text}"}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500
                }
            )

            response.raise_for_status()
            data = response.json()

            # Extraer respuesta
            content = data["choices"][0]["message"]["content"]

            # Parsear JSON de la respuesta
            return self._parse_ai_response(content)

    async def _call_openai(self, text: str) -> Dict[str, Any]:
        """Llama a la API de OpenAI como fallback"""
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [
                        {"role": "system", "content": SOCMINT_SYSTEM_PROMPT},
                        {"role": "user", "content": f"Analiza este texto:\n\n{text}"}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500
                }
            )

            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]
            return self._parse_ai_response(content)

    def _parse_ai_response(self, content: str) -> Dict[str, Any]:
        """Parsea la respuesta JSON de la IA"""
        try:
            # Intentar extraer JSON del contenido
            content = content.strip()

            # Si viene envuelto en ```json ... ```, extraerlo
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content)

        except json.JSONDecodeError:
            # Si falla el parse, extraer valores con regex
            return {
                "sentiment": self._extract_number(content, r'"sentiment":\s*([-\d.]+)') or 0,
                "category": self._extract_string(content, r'"category":\s*"([^"]+)"') or "Otros",
                "risk_level": self._extract_string(content, r'"risk_level":\s*"([^"]+)"') or "Bajo",
                "summary": self._extract_string(content, r'"summary":\s*"([^"]+)"') or "Error en análisis",
                "intent": self._extract_string(content, r'"intent":\s*"([^"]+)"') or "Informar"
            }

    def _extract_number(self, text: str, pattern: str) -> Optional[float]:
        match = re.search(pattern, text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return None

    def _extract_string(self, text: str, pattern: str) -> Optional[str]:
        match = re.search(pattern, text)
        return match.group(1) if match else None

    def _basic_analysis(self, text: str) -> Dict[str, Any]:
        """Análisis básico sin IA (fallback)"""
        text_lower = text.lower()

        # Sentiment básico por palabras
        positive_words = ["bueno", "excelente", "positivo", "avance", "logro", "éxito", "beneficio"]
        negative_words = ["malo", "terrible", "negativo", "problema", "crisis", "corrupción", "fraude"]

        pos_count = sum(1 for w in positive_words if w in text_lower)
        neg_count = sum(1 for w in negative_words if w in text_lower)

        if pos_count > neg_count:
            sentiment = 0.3
        elif neg_count > pos_count:
            sentiment = -0.3
        else:
            sentiment = 0

        # Categoría básica
        if any(w in text_lower for w in ["seguridad", "policía", "delito", "crimen"]):
            category = "Seguridad"
        elif any(w in text_lower for w in ["economía", "dinero", "empleo", "trabajo"]):
            category = "Economía"
        elif any(w in text_lower for w in ["corrupción", "fraude", "robo"]):
            category = "Corrupción"
        else:
            category = "Otros"

        return {
            "sentiment": sentiment,
            "category": category,
            "risk_level": "Bajo",
            "summary": text[:100] + "..." if len(text) > 100 else text,
            "intent": "Informar"
        }

    # =========================================================================
    # HELPERS
    # =========================================================================
    def _get_campaign_keywords(self, campaign) -> List[str]:
        """Extrae keywords de una campaña"""
        keywords = []

        # Query principal (nombre del candidato)
        if campaign.query:
            keywords.append(campaign.query)
            # También agregar partes del nombre
            keywords.extend([p for p in campaign.query.split() if len(p) > 2])

        # Variantes de búsqueda si existen
        if campaign.search_variants:
            keywords.extend(campaign.search_variants)

        # Keywords de ciudad si existen
        if campaign.city_keywords:
            keywords.extend(campaign.city_keywords)

        return list(set(keywords))  # Eliminar duplicados

    def _find_keyword_matches(self, text: str, keywords: List[str]) -> List[str]:
        """Encuentra qué keywords aparecen en el texto"""
        if not text:
            return []

        text_lower = text.lower()
        matches = []

        for keyword in keywords:
            if keyword.lower() in text_lower:
                matches.append(keyword)

        return matches

    def _map_category(self, category_str: Optional[str]) -> Optional[str]:
        """Mapea string de categoría al enum"""
        from ..models import AnalysisCategory

        if not category_str:
            return None

        category_map = {
            "seguridad": AnalysisCategory.SEGURIDAD,
            "economía": AnalysisCategory.ECONOMIA,
            "economia": AnalysisCategory.ECONOMIA,
            "ataque": AnalysisCategory.ATAQUE,
            "gestión": AnalysisCategory.GESTION,
            "gestion": AnalysisCategory.GESTION,
            "corrupción": AnalysisCategory.CORRUPCION,
            "corrupcion": AnalysisCategory.CORRUPCION,
            "otros": AnalysisCategory.OTROS,
        }

        return category_map.get(category_str.lower(), AnalysisCategory.OTROS)

    def _map_risk_level(self, risk_str: Optional[str]) -> Optional[str]:
        """Mapea string de riesgo al enum"""
        from ..models import AnalysisRiskLevel

        if not risk_str:
            return None

        risk_map = {
            "bajo": AnalysisRiskLevel.BAJO,
            "medio": AnalysisRiskLevel.MEDIO,
            "alto": AnalysisRiskLevel.ALTO,
            "crítico": AnalysisRiskLevel.CRITICO,
            "critico": AnalysisRiskLevel.CRITICO,
        }

        return risk_map.get(risk_str.lower(), AnalysisRiskLevel.BAJO)

    def _map_intent(self, intent_str: Optional[str]) -> Optional[str]:
        """Mapea string de intención al enum"""
        from ..models import AnalysisIntent

        if not intent_str:
            return None

        intent_map = {
            "informar": AnalysisIntent.INFORMAR,
            "movilizar": AnalysisIntent.MOVILIZAR,
            "difamar": AnalysisIntent.DIFAMAR,
        }

        return intent_map.get(intent_str.lower(), AnalysisIntent.INFORMAR)


# =========================================================================
# FUNCIONES HELPER
# =========================================================================
async def process_new_data(
    db: AsyncSession,
    limit: int = 100,
    campaign_id: Optional[str] = None
) -> Dict[str, Any]:
    """Helper para procesar nuevos datos (Momento A)"""
    engine = AnalysisEngine(db)
    return await engine.process_new_scrapes(limit=limit, campaign_id=campaign_id)


async def run_campaign_backfill(
    db: AsyncSession,
    campaign_id: str,
    limit: int = 1000
) -> Dict[str, Any]:
    """Helper para retro-análisis de campaña (Momento B)"""
    engine = AnalysisEngine(db)
    return await engine.run_backfill_for_campaign(campaign_id=campaign_id, limit=limit)


async def get_campaign_summary(
    db: AsyncSession,
    campaign_id: str,
    days_back: int = 7
) -> Dict[str, Any]:
    """
    Genera un resumen de análisis para una campaña basado en campaign_analyses.

    Args:
        db: Sesión de base de datos
        campaign_id: ID de la campaña
        days_back: Días hacia atrás para el resumen

    Returns:
        Diccionario con resumen ejecutivo, métricas, etc.
    """
    from datetime import timedelta
    from collections import Counter
    from ..models import CampaignAnalysis, RawScrapeData, Campaign

    print(f"\n📊 Generando resumen para campaña {campaign_id}...")

    # Obtener campaña
    campaign_result = await db.execute(
        select(Campaign).where(Campaign.id == campaign_id)
    )
    campaign = campaign_result.scalar_one_or_none()
    campaign_name = campaign.name if campaign else "Desconocida"

    # Calcular fecha límite
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)

    # Obtener análisis de la campaña CON datos del post original
    from sqlalchemy.orm import selectinload

    query = (
        select(CampaignAnalysis)
        .options(selectinload(CampaignAnalysis.rawData))  # JOIN con raw_scrape_data
        .where(
            and_(
                CampaignAnalysis.campaignId == campaign_id,
                CampaignAnalysis.analyzedAt >= cutoff_date
            )
        )
        .order_by(CampaignAnalysis.analyzedAt.desc())
    )

    result = await db.execute(query)
    analyses = result.scalars().all()

    print(f"   📋 Análisis encontrados: {len(analyses)}")

    if not analyses:
        # Si no hay análisis, devolver estructura vacía
        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "total_posts": 0,
            "executive_summary": f"No se encontraron datos para {campaign_name} en los últimos {days_back} días.",
            "strategic_analysis": "Sin datos suficientes para análisis estratégico.",
            "recommendations": ["Verificar las fuentes de monitoreo configuradas."],
            "evidence_log": [],
            "sentiment_distribution": {"positive": 0, "negative": 0, "neutral": 0},
            "risk_distribution": {"bajo": 0, "medio": 0, "alto": 0, "critico": 0},
            "total_engagement": {"likes": 0, "shares": 0, "comments": 0},
            "top_topics": [],
            "generated_at": datetime.now(timezone.utc).isoformat()
        }

    # Procesar métricas
    sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
    risk_counts = {"bajo": 0, "medio": 0, "alto": 0, "critico": 0}
    categories = []
    all_keywords = []
    evidence_log = []
    total_likes = 0
    total_shares = 0
    total_comments = 0

    for analysis in analyses:
        # Sentimiento
        if analysis.sentimentScore is not None:
            if analysis.sentimentScore > 0.2:
                sentiment_counts["positive"] += 1
            elif analysis.sentimentScore < -0.2:
                sentiment_counts["negative"] += 1
            else:
                sentiment_counts["neutral"] += 1

        # Riesgo
        if analysis.riskLevel:
            risk_key = analysis.riskLevel.value.lower() if hasattr(analysis.riskLevel, 'value') else str(analysis.riskLevel).lower()
            if risk_key in risk_counts:
                risk_counts[risk_key] += 1

        # Categorías
        if analysis.category:
            cat_value = analysis.category.value if hasattr(analysis.category, 'value') else str(analysis.category)
            categories.append(cat_value)

        # Keywords
        if analysis.matchedKeywords:
            all_keywords.extend(analysis.matchedKeywords)

        # Evidencia - mostrar claramente TEMA y POSTURA (a favor/en contra)
        raw = analysis.rawData  # El post original de raw_scrape_data
        post_extract = None
        if raw and raw.rawText:
            post_extract = raw.rawText[:300] + "..." if len(raw.rawText) > 300 else raw.rawText

        # Determinar postura (a favor / en contra / neutral)
        score = analysis.sentimentScore or 0
        if score > 0.2:
            postura = "A FAVOR"
        elif score < -0.2:
            postura = "EN CONTRA"
        else:
            postura = "NEUTRAL"

        # Categoría/Tema legible
        tema = analysis.category.value if analysis.category and hasattr(analysis.category, 'value') else str(analysis.category or "General")

        evidence_log.append({
            "tema": tema,
            "postura": postura,
            "resumen": analysis.summary or "Sin resumen",
            "extracto": post_extract,
            "url": raw.postUrl if raw else None,
            "fecha": raw.postDate.strftime("%d/%m/%Y") if raw and raw.postDate else None,
            "riesgo": analysis.riskLevel.value if analysis.riskLevel and hasattr(analysis.riskLevel, 'value') else str(analysis.riskLevel or "bajo"),
        })

    # Calcular top topics por categoría
    category_counts = Counter(categories)
    top_topics = [{"tema": cat, "menciones": count} for cat, count in category_counts.most_common(5)]

    # Keyword más frecuentes
    keyword_counts = Counter(all_keywords)
    top_keywords = [kw for kw, _ in keyword_counts.most_common(10)]

    # Determinar sentimiento predominante
    max_sentiment = max(sentiment_counts, key=sentiment_counts.get)
    total_posts = len(analyses)

    # Determinar nivel de riesgo general
    if risk_counts["critico"] > 0:
        overall_risk = "CRÍTICO"
    elif risk_counts["alto"] > total_posts * 0.2:
        overall_risk = "ALTO"
    elif risk_counts["medio"] > total_posts * 0.3:
        overall_risk = "MEDIO"
    else:
        overall_risk = "BAJO"

    # Generar resumen ejecutivo
    executive_summary = f"""Análisis de {campaign_name} - Últimos {days_back} días:
Se analizaron {total_posts} publicaciones.
Sentimiento predominante: {max_sentiment} ({sentiment_counts[max_sentiment]} menciones).
Nivel de riesgo general: {overall_risk}.
Categorías principales: {', '.join([t['tema'] for t in top_topics[:3]]) if top_topics else 'N/A'}."""

    # Generar análisis estratégico
    strategic_analysis = f"""
El monitoreo de redes sociales para {campaign_name} muestra una distribución de sentimiento:
- Positivo: {sentiment_counts['positive']} ({round(sentiment_counts['positive']/total_posts*100, 1)}%)
- Negativo: {sentiment_counts['negative']} ({round(sentiment_counts['negative']/total_posts*100, 1)}%)
- Neutral: {sentiment_counts['neutral']} ({round(sentiment_counts['neutral']/total_posts*100, 1)}%)

Distribución de riesgo reputacional:
- Bajo: {risk_counts['bajo']}
- Medio: {risk_counts['medio']}
- Alto: {risk_counts['alto']}
- Crítico: {risk_counts['critico']}

Palabras clave más mencionadas: {', '.join(top_keywords[:5]) if top_keywords else 'N/A'}
"""

    # Generar recomendaciones
    recommendations = []
    if sentiment_counts["negative"] > sentiment_counts["positive"]:
        recommendations.append("Considerar estrategia de comunicación para mejorar percepción.")
    if risk_counts["alto"] + risk_counts["critico"] > 0:
        recommendations.append(f"Revisar {risk_counts['alto'] + risk_counts['critico']} publicaciones de alto riesgo identificadas.")
    if total_posts < 10:
        recommendations.append("Aumentar fuentes de monitoreo para obtener más datos.")
    recommendations.append("Continuar monitoreo activo de las fuentes configuradas.")

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "total_posts": total_posts,
        "executive_summary": executive_summary,
        "strategic_analysis": strategic_analysis,
        "recommendations": recommendations,
        "evidence_log": evidence_log[:50],  # Limitar a 50 para el reporte
        "sentiment_distribution": sentiment_counts,
        "risk_distribution": risk_counts,
        "total_engagement": {
            "likes": total_likes,
            "shares": total_shares,
            "comments": total_comments
        },
        "top_topics": top_topics,
        "top_keywords": top_keywords,
        "overall_risk": overall_risk,
        "predominant_sentiment": max_sentiment,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }
