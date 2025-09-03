from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String,
    DateTime,
    Boolean,
    Integer,
    ForeignKey,
    JSON,
    Text,
    Enum,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, declarative_base

Base = declarative_base()
from sqlalchemy.orm import Mapped, mapped_column, relationship, declarative_base

Base = declarative_base()

from .db import Base

class SourceType(str, enum.Enum):
    NEWS = "NEWS"
    FACEBOOK = "FACEBOOK"
    INSTAGRAM = "INSTAGRAM"
    X = "X"
    YOUTUBE = "YOUTUBE"
    TIKTOK = "TIKTOK"

class ItemStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    FETCHED = "FETCHED"
    ANALYZED = "ANALYZED"
    ERROR = "ERROR"

class User(Base):
    __tablename__ = "User"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(String, default="admin")
    createdAt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="owner")

class Campaign(Base):
    __tablename__ = "Campaign"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ownerId: Mapped[str] = mapped_column(String, ForeignKey("User.id"))
    owner: Mapped[User] = relationship(back_populates="campaigns")
    createdAt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sources: Mapped[list["SourceLink"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    items: Mapped[list["IngestedItem"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")
    analyses: Mapped[list["Analysis"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")

class SourceLink(Base):
    __tablename__ = "SourceLink"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    campaignId: Mapped[str] = mapped_column(String, ForeignKey("Campaign.id"))
    campaign: Mapped[Campaign] = relationship(back_populates="sources")
    type: Mapped[SourceType] = mapped_column(Enum(SourceType))
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String)
    isActive: Mapped[bool] = mapped_column(Boolean, default=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updatedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_source_campaign_type", "campaignId", "type"),
        UniqueConstraint("campaignId", "url", name="uq_source_campaign_url"),
    )

class IngestedItem(Base):
    __tablename__ = "IngestedItem"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    campaignId: Mapped[str] = mapped_column(String, ForeignKey("Campaign.id"))
    campaign: Mapped[Campaign] = relationship(back_populates="items")
    sourceType: Mapped[SourceType] = mapped_column(Enum(SourceType))
    sourceUrl: Mapped[str] = mapped_column(String)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    contentUrl: Mapped[str] = mapped_column(String)
    publishedAt: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fetchedAt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[ItemStatus] = mapped_column(Enum(ItemStatus), default=ItemStatus.QUEUED)
    hash: Mapped[str] = mapped_column(String, unique=True)

    analyses: Mapped[list["Analysis"]] = relationship(back_populates="item", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_item_campaign_source_status", "campaignId", "sourceType", "status"),
        Index("idx_item_publishedAt", "publishedAt"),
    )

class Analysis(Base):
    __tablename__ = "Analysis"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    campaignId: Mapped[str] = mapped_column(String, ForeignKey("Campaign.id"))
    campaign: Mapped[Campaign] = relationship(back_populates="analyses")

    itemId: Mapped[str | None] = mapped_column(String, ForeignKey("IngestedItem.id"), nullable=True)
    item: Mapped["IngestedItem | None"] = relationship(back_populates="analyses")

    model: Mapped[str] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[float | None] = mapped_column(Float, nullable=True)
    stance: Mapped[str | None] = mapped_column(String, nullable=True)
    topics: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    entities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    createdAt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_analysis_campaign_createdAt", "campaignId", "createdAt"),
        Index("idx_analysis_item", "itemId"),
    )
    from sqlalchemy import String, DateTime, Boolean, Integer, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
import datetime, uuid

class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: str(uuid.uuid4()))
    userId: Mapped[str] = mapped_column(String(50), ForeignKey("users.id"), index=True)
    campaignId: Mapped[str | None] = mapped_column(String(40), ForeignKey("campaigns.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    scheduleCron: Mapped[str] = mapped_column(String(80), default="0 12 * * *")  # diario 12:00
    timezone: Mapped[str] = mapped_column(String(64), default="America/Monterrey")
    analyze: Mapped[bool] = mapped_column(Boolean, default=True)  # analizar con LLM
    isActive: Mapped[bool] = mapped_column(Boolean, default=True)
    createdAt: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)

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
    createdAt: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    itemsCount: Mapped[int] = mapped_column(Integer, default=0)
    # opcional: resumen global del batch
    aggregate: Mapped[dict | None] = mapped_column(JSON, nullable=True)