from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    DateTime,
    Boolean,
    Integer,
    Float,
    ForeignKey,
    JSON,
    Text,
    Enum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, declarative_base

Base = declarative_base()

class PlanTier(enum.Enum):
    BASIC = "BASIC"        # 1 auto update / day
    PRO = "PRO"            # 3 auto updates / day
    UNLIMITED = "UNLIMITED"# unlimited

# ------------------------
# User
# ------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Admin & subscription
    isAdmin: Mapped[bool] = mapped_column(Boolean, default=False)
    plan: Mapped[PlanTier] = mapped_column(Enum(PlanTier), default=PlanTier.BASIC)
    # Feature flags at user level (overrides): {"comparator": true, "connectors": false}
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# ------------------------
# Campaign
# ------------------------
class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    query: Mapped[str] = mapped_column(String(300), nullable=False)
    size: Mapped[int] = mapped_column(Integer, default=35)
    days_back: Mapped[int] = mapped_column(Integer, default=30)
    lang: Mapped[str] = mapped_column(String(16), default="es-419")
    country: Mapped[str] = mapped_column(String(8), default="MX")
    city_keywords: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Admin & subscription
    plan: Mapped[PlanTier] = mapped_column(Enum(PlanTier), default=PlanTier.BASIC)

    # Auto-update scheduling
    autoEnabled: Mapped[bool] = mapped_column(Boolean, default=True)
    autoRunsToday: Mapped[int] = mapped_column(Integer, default=0)
    autoLastReset: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lastAutoRunAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Variantes de búsqueda generadas (lista de strings)
    search_variants: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Nuevo: análisis rápido de noticias (avg_sentiment, artículos, etc.)
    news_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    userId: Mapped[str | None] = mapped_column(String(50), ForeignKey("users.id"))
    user = relationship("User")

    sources = relationship("SourceLink", back_populates="campaign")
    analyses = relationship("Analysis", back_populates="campaign")


# ------------------------
# SourceLink
# ------------------------
class SourceType(enum.Enum):
    NEWS = "NEWS"
    RSS = "RSS"
    TWITTER = "TWITTER"
    OTHER = "OTHER"


class SourceLink(Base):
    __tablename__ = "source_links"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    campaignId: Mapped[str | None] = mapped_column(String(40), ForeignKey("campaigns.id"), index=True, nullable=True)
    type: Mapped[SourceType] = mapped_column(Enum(SourceType), nullable=False, default=SourceType.NEWS)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Admin & subscription
    isAdmin: Mapped[bool] = mapped_column(Boolean, default=False)
    plan: Mapped[PlanTier] = mapped_column(Enum(PlanTier), default=PlanTier.BASIC)
    # Feature flags at user level (overrides): {"comparator": true, "connectors": false}
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Importante: dejamos __table_args__ vacío para que los índices/unique
    # se creen de forma idempotente en main.py (IF NOT EXISTS).
    __table_args__ = ()

    campaign = relationship("Campaign", back_populates="sources", lazy="joined")


# ------------------------
# IngestedItem
# ------------------------
class ItemStatus(enum.Enum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    ERROR = "ERROR"


class IngestedItem(Base):
    __tablename__ = "ingested_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    sourceId: Mapped[str | None] = mapped_column(String(40), ForeignKey("source_links.id"))
    campaignId: Mapped[str | None] = mapped_column(String(40), ForeignKey("campaigns.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    publishedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[ItemStatus | None] = mapped_column(Enum(ItemStatus), nullable=True, default=None)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Admin & subscription
    isAdmin: Mapped[bool] = mapped_column(Boolean, default=False)
    plan: Mapped[PlanTier] = mapped_column(Enum(PlanTier), default=PlanTier.BASIC)
    # Feature flags at user level (overrides): {"comparator": true, "connectors": false}
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    analysis = relationship("Analysis", back_populates="item", uselist=False, cascade="all, delete-orphan")


# ------------------------
# Analysis
# ------------------------
class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    campaignId: Mapped[str] = mapped_column(String(40), ForeignKey("campaigns.id"), index=True)
    itemId: Mapped[str] = mapped_column(String(40), ForeignKey("ingested_items.id"), unique=True)

    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    tone: Mapped[str | None] = mapped_column(String(50))
    topics: Mapped[list[str] | None] = mapped_column(JSON)
    summary: Mapped[str | None] = mapped_column(Text)
    entities: Mapped[dict | None] = mapped_column(JSON)
    stance: Mapped[str | None] = mapped_column(String(50))
    perception: Mapped[dict | None] = mapped_column(JSON)
    # Metadata adicional del análisis (source, scoring, etc.)
    metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Admin & subscription
    isAdmin: Mapped[bool] = mapped_column(Boolean, default=False)
    plan: Mapped[PlanTier] = mapped_column(Enum(PlanTier), default=PlanTier.BASIC)
    # Feature flags at user level (overrides): {"comparator": true, "connectors": false}
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    campaign = relationship("Campaign", back_populates="analyses")
    item = relationship("IngestedItem", back_populates="analysis")


# ------------------------
# Plan / Subscription
# ------------------------
class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    maxResultsPerSearch: Mapped[int] = mapped_column(Integer, default=25)
    maxDaysBack: Mapped[int] = mapped_column(Integer, default=14)
    maxConcurrentAnalyses: Mapped[int] = mapped_column(Integer, default=5)
    notes: Mapped[str] = mapped_column(Text, default="")
    isActive: Mapped[bool] = mapped_column(Boolean, default=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Admin & subscription
    isAdmin: Mapped[bool] = mapped_column(Boolean, default=False)
    plan: Mapped[PlanTier] = mapped_column(Enum(PlanTier), default=PlanTier.BASIC)
    # Feature flags at user level (overrides): {"comparator": true, "connectors": false}
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    userId: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"), index=True)
    planId: Mapped[str] = mapped_column(String(40), ForeignKey("plans.id"), index=True)
    isActive: Mapped[bool] = mapped_column(Boolean, default=True)
    startedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    endsAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user = relationship("User")
    plan = relationship("Plan")


# ------------------------
# Alerts
# ------------------------
class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    userId: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"), index=True)
    isActive: Mapped[bool] = mapped_column(Boolean, default=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    # Admin & subscription
    isAdmin: Mapped[bool] = mapped_column(Boolean, default=False)
    plan: Mapped[PlanTier] = mapped_column(Enum(PlanTier), default=PlanTier.BASIC)
    # Feature flags at user level (overrides): {"comparator": true, "connectors": false}
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    user = relationship("User")


class AlertQuery(Base):
    __tablename__ = "alert_queries"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    alertId: Mapped[str] = mapped_column(String(40), ForeignKey("alerts.id"), index=True)
    q: Mapped[str] = mapped_column(String(300))
    country: Mapped[str] = mapped_column(String(8), default="MX")
    lang: Mapped[str] = mapped_column(String(16), default="es-419")
    daysBack: Mapped[int] = mapped_column(Integer, default=14)
    size: Mapped[int] = mapped_column(Integer, default=35)
    cityKeywords: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)


class AlertNotification(Base):
    __tablename__ = "alert_notifications"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    alertId: Mapped[str] = mapped_column(String(40), ForeignKey("alerts.id"), index=True)
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


# ------------------------
# ActorReport (Histórico de Reportes)
# ------------------------
class ReportType(str, enum.Enum):
    """Tipos de reportes disponibles"""
    WEEKLY = "weekly"
    DAILY = "daily"


class ActorReport(Base):
    """
    Almacena reportes históricos de actores políticos.
    Cada vez que se genera un reporte, se guarda aquí.
    Esto permite:
    - Ver histórico completo de un actor
    - Comparar reportes en el tiempo
    - No regenerar reportes recientes (cache)
    """
    __tablename__ = "actor_reports"

    id: Mapped[str] = mapped_column(
        String(40), 
        primary_key=True, 
        default=lambda: str(uuid.uuid4())
    )
    
    actorName: Mapped[str] = mapped_column(
        String(200), 
        index=True,
        nullable=False
    )
    
    reportType: Mapped[ReportType] = mapped_column(
        Enum(ReportType),
        index=True,
        nullable=False
    )
    
    reportData: Mapped[dict] = mapped_column(
        JSON,
        nullable=False
    )
    
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )
    
    createdAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        index=True,
        nullable=False
    )
    
    # Metadatos adicionales
    generationTime: Mapped[float | None] = mapped_column(
        Float,
        nullable=True
    )
    
    itemCount: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True
    )

    def __repr__(self):
        return f"<ActorReport {self.reportType.value} for {self.actorName} at {self.createdAt}>"


# ------------------------
# MonitoringSource - Fuentes de redes sociales para monitoreo con Apify
# ------------------------
class SocialPlatform(str, enum.Enum):
    """Plataformas de redes sociales soportadas"""
    FACEBOOK = "facebook"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"


class MonitoringStatus(str, enum.Enum):
    """Estado del monitoreo de una fuente"""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    PENDING = "pending"


class MonitoringSource(Base):
    """
    Fuentes de inteligencia para monitoreo de redes sociales.
    Cada fuente representa una URL específica (página de FB, cuenta de Twitter, etc.)
    que será rastreada por Apify.
    """
    __tablename__ = "monitoring_sources"

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    campaignId: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("campaigns.id"),
        index=True,
        nullable=False
    )

    # URL de la fuente (página de FB, perfil de Twitter, etc.)
    url: Mapped[str] = mapped_column(Text, nullable=False)

    # Tipo de plataforma
    platform: Mapped[SocialPlatform] = mapped_column(
        Enum(SocialPlatform),
        nullable=False
    )

    # Nombre descriptivo de la fuente (ej: "Página oficial de Juan Pérez")
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Estado del monitoreo
    status: Mapped[MonitoringStatus] = mapped_column(
        Enum(MonitoringStatus),
        default=MonitoringStatus.ACTIVE
    )

    # Configuración de Apify
    apifyActorId: Mapped[str | None] = mapped_column(String(100), nullable=True)
    apifyConfig: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Tracking de ejecuciones
    lastRunAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lastRunStatus: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lastRunPostsCount: Mapped[int | None] = mapped_column(Integer, nullable=True)
    totalPostsCollected: Mapped[int] = mapped_column(Integer, default=0)

    # Error tracking
    lastError: Mapped[str | None] = mapped_column(Text, nullable=True)
    errorCount: Mapped[int] = mapped_column(Integer, default=0)

    createdAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow
    )
    updatedAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Relaciones
    campaign = relationship("Campaign", backref="monitoring_sources")
    analytic_results = relationship("AnalyticResult", back_populates="source", cascade="all, delete-orphan")


# ------------------------
# AnalyticResult - Resultados de análisis de posts de redes sociales
# ------------------------
class RiskLevel(str, enum.Enum):
    """Nivel de riesgo detectado"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AnalyticResult(Base):
    """
    Resultados del análisis de IA sobre posts de redes sociales.
    Cada registro representa un post analizado con su sentimiento,
    narrativa y nivel de riesgo.
    """
    __tablename__ = "analytic_results"

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    # Relación con la fuente de monitoreo
    sourceId: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("monitoring_sources.id"),
        index=True,
        nullable=False
    )

    # Relación con la campaña (para queries directas)
    campaignId: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("campaigns.id"),
        index=True,
        nullable=False
    )

    # Datos del post original (de Apify)
    postId: Mapped[str | None] = mapped_column(String(100), nullable=True)  # ID único del post en la plataforma
    postUrl: Mapped[str | None] = mapped_column(Text, nullable=True)
    postContent: Mapped[str | None] = mapped_column(Text, nullable=True)
    postAuthor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    postDate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Métricas de engagement (de Apify)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Resultados del análisis de IA
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)  # positive, negative, neutral
    sentimentScore: Mapped[float | None] = mapped_column(Float, nullable=True)  # -1.0 a 1.0

    # Narrativa/Temas detectados
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    topics: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Análisis de riesgo
    riskLevel: Mapped[RiskLevel | None] = mapped_column(Enum(RiskLevel), nullable=True)
    riskScore: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    riskFactors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Entidades mencionadas
    entities: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Resumen generado por IA
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata del análisis
    analysisModel: Mapped[str | None] = mapped_column(String(50), nullable=True)  # perplexity, openai, etc.
    analysisTokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rawApifyData: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Datos crudos de Apify
    rawAIResponse: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Respuesta cruda de la IA

    # Flags para filtrado
    isRelevant: Mapped[bool] = mapped_column(Boolean, default=True)
    isProcessed: Mapped[bool] = mapped_column(Boolean, default=False)
    requiresAttention: Mapped[bool] = mapped_column(Boolean, default=False)

    createdAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        index=True
    )

    # Relaciones
    source = relationship("MonitoringSource", back_populates="analytic_results")
    campaign = relationship("Campaign", backref="analytic_results")


# ------------------------
# ApifyRun - Tracking de ejecuciones de Apify
# ------------------------
class ApifyRunStatus(str, enum.Enum):
    """Estado de una ejecución de Apify"""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABORTED = "aborted"


class ApifyRun(Base):
    """
    Tracking de ejecuciones de Apify Actors.
    Permite monitorear el estado y resultados de cada ejecución.
    """
    __tablename__ = "apify_runs"

    id: Mapped[str] = mapped_column(
        String(40),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    # ID de la ejecución en Apify
    apifyRunId: Mapped[str] = mapped_column(String(100), index=True, nullable=False)

    # Relación con campaña (puede procesar múltiples fuentes)
    campaignId: Mapped[str] = mapped_column(
        String(40),
        ForeignKey("campaigns.id"),
        index=True,
        nullable=False
    )

    # Actor de Apify usado
    actorId: Mapped[str] = mapped_column(String(100), nullable=False)

    # Estado de la ejecución
    status: Mapped[ApifyRunStatus] = mapped_column(
        Enum(ApifyRunStatus),
        default=ApifyRunStatus.QUEUED
    )

    # Configuración de la ejecución
    inputConfig: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Resultados
    postsFound: Mapped[int | None] = mapped_column(Integer, nullable=True)
    postsAnalyzed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timing
    startedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finishedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Costos y uso
    computeUnits: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Error tracking
    errorMessage: Mapped[str | None] = mapped_column(Text, nullable=True)

    createdAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow
    )

    # Relaciones
    campaign = relationship("Campaign", backref="apify_runs")