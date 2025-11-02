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
        String, 
        primary_key=True, 
        default=lambda: str(uuid.uuid4())
    )
    
    actorName: Mapped[str] = mapped_column(
        String, 
        index=True,
        nullable=False,
        comment="Nombre del actor político (ej: 'Samuel García')"
    )
    
    reportType: Mapped[ReportType] = mapped_column(
        Enum(ReportType),
        index=True,
        nullable=False,
        comment="Tipo de reporte: 'weekly' o 'daily'"
    )
    
    reportData: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="Datos completos del reporte en formato JSON"
    )
    
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Resumen rápido del reporte para búsquedas"
    )
    
    createdAt: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        index=True,
        nullable=False
    )
    
    # Metadatos adicionales
    generationTime: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="Tiempo que tomó generar el reporte (segundos)"
    )
    
    itemCount: Mapped[int | None] = mapped_column(
        nullable=True,
        comment="Número de items/evidencias en el reporte"
    )

    def __repr__(self):
        return f"<ActorReport {self.reportType.value} for {self.actorName} at {self.createdAt}>"