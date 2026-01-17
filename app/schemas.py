# app/schemas.py
from __future__ import annotations
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, HttpUrl


# =========================================================
# Enums compartidos
# =========================================================
class PlanTierEnum(str, Enum):
    BASIC = "BASIC"
    PRO = "PRO"
    UNLIMITED = "UNLIMITED"


class SourceTypeEnum(str, Enum):
    NEWS = "NEWS"
    RSS = "RSS"
    TWITTER = "TWITTER"
    OTHER = "OTHER"


class ItemStatusEnum(str, Enum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"
    ERROR = "ERROR"


# =========================================================
# Campaign
# =========================================================
class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    query: str = Field(..., min_length=1, max_length=300)
    size: int = 35
    days_back: int = Field(30, alias="days_back")
    lang: str = "es-419"
    country: str = "MX"
    city_keywords: Optional[List[str]] = None
    plan: PlanTierEnum = PlanTierEnum.BASIC
    autoEnabled: bool = True

    class Config:
        populate_by_name = True  # acepta days_back o daysBack


class MonitoringSourceBrief(BaseModel):
    """Versión resumida de MonitoringSource para incluir en CampaignOut"""
    id: str
    url: str
    platform: str
    name: Optional[str] = None
    status: str
    lastRunAt: Optional[datetime] = None
    totalPostsCollected: int = 0

    class Config:
        from_attributes = True


class CampaignOut(BaseModel):
    id: str
    name: str
    query: str
    size: int
    days_back: int
    lang: str
    country: str
    city_keywords: Optional[List[str]] = None
    plan: PlanTierEnum = PlanTierEnum.BASIC
    autoEnabled: bool = True
    userId: Optional[str] = None
    createdAt: Optional[datetime] = None
    news_analysis: Optional[Dict[str, Any]] = None
    # Fuentes de monitoreo de redes sociales asociadas
    monitoring_sources: Optional[List[MonitoringSourceBrief]] = None
    monitoring_sources_count: int = 0

    class Config:
        from_attributes = True


# =========================================================
# Sources
# =========================================================
class SourceCreate(BaseModel):
    type: SourceTypeEnum = Field(default=SourceTypeEnum.NEWS)
    url: str = Field(..., min_length=5)
    campaignId: Optional[str] = None


class SourceOut(BaseModel):
    id: str
    campaignId: Optional[str] = None
    type: SourceTypeEnum
    url: str
    createdAt: Optional[datetime] = None

    class Config:
        from_attributes = True


# =========================================================
# Ingest (ingesta de noticias/links)
# =========================================================
class IngestCreate(BaseModel):
    """
    Petición para lanzar ingesta.
    - Por campaignId (usa config guardada)
    - Ad-hoc: con q/size/days_back/lang/country/city_keywords
    """
    campaignId: Optional[str] = None

    # Parámetros ad-hoc (si no hay campaignId)
    q: Optional[str] = None
    size: int = 35
    days_back: int = Field(30, alias="days_back")
    lang: str = "es-419"
    country: str = "MX"
    city_keywords: Optional[List[str]] = None
    plan: PlanTierEnum = PlanTierEnum.BASIC
    autoEnabled: bool = True

    # Fuentes opcionales (urls directas)
    sources: Optional[List[str]] = None

    class Config:
        populate_by_name = True


class IngestedItemOut(BaseModel):
    id: str
    sourceId: Optional[str] = None
    campaignId: Optional[str] = None
    title: str
    url: str
    publishedAt: Optional[datetime] = None
    status: Optional[ItemStatusEnum] = None
    createdAt: Optional[datetime] = None

    class Config:
        from_attributes = True


class IngestResult(BaseModel):
    created_count: int = 0
    items: Optional[List[IngestedItemOut]] = None


# =========================================================
# Analyses (resultados de análisis)
# =========================================================
class AnalysisOut(BaseModel):
    id: str
    campaignId: str
    itemId: Optional[str] = None
    sentiment: Optional[float] = None
    tone: Optional[str] = None
    topics: Optional[List[str]] = None
    summary: Optional[str] = None
    entities: Optional[Dict[str, Any]] = None
    stance: Optional[str] = None
    perception: Optional[Dict[str, Any]] = None
    createdAt: Optional[datetime] = None

    class Config:
        from_attributes = True


# =========================================================
# AI / LLM (análisis con modelo)
# =========================================================
class AIAnalysisInput(BaseModel):
    title: str
    summary: str
    actor: str
    language: str = "es"


class AIAnalysisResult(BaseModel):
    sentiment: Optional[float] = None        # -1..1
    tone: Optional[str] = None               # e.g., "crítico", "neutral"
    topics: Optional[List[str]] = None
    key_points: Optional[List[str]] = None
    perception: Optional[Dict[str, Any]] = None  # dict con señales/razones
    verdict: Optional[str] = None            # mini conclusión del snippet


# =========================================================
# News Search (Google News u otras)
# =========================================================
class NewsSearchParams(BaseModel):
    q: str
    size: int = 35
    days_back: int = Field(30, alias="days_back")
    lang: str = "es-419"
    country: str = "MX"
    city_keywords: Optional[List[str]] = None
    plan: PlanTierEnum = PlanTierEnum.BASIC
    autoEnabled: bool = True

    class Config:
        populate_by_name = True


class NewsItem(BaseModel):
    title: str
    url: str
    source: Optional[str] = None
    publishedAt: Optional[datetime] = None
    snippet: Optional[str] = None


class NewsSearchResponse(BaseModel):
    count: int
    items: List[NewsItem]


# =========================================================
# Genéricos (opcional)
# =========================================================
class ErrorResponse(BaseModel):
    detail: str

# =========================================================
# Admin - Users
# =========================================================
class AdminUserCreate(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    isAdmin: bool = False
    plan: PlanTierEnum = PlanTierEnum.BASIC
    features: Optional[Dict[str, Any]] = None

class AdminUserUpdate(BaseModel):
    name: Optional[str] = None
    isAdmin: Optional[bool] = None
    plan: Optional[PlanTierEnum] = None
    features: Optional[Dict[str, Any]] = None

class AdminUserOut(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    isAdmin: bool = False
    plan: PlanTierEnum = PlanTierEnum.BASIC
    features: Optional[Dict[str, Any]] = None
    createdAt: Optional[datetime] = None
    class Config:
        from_attributes = True

# =========================================================
# Campaign Update (Admin)
# =========================================================
class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    query: Optional[str] = None
    size: Optional[int] = None
    days_back: Optional[int] = Field(default=None, alias="days_back")
    lang: Optional[str] = None
    country: Optional[str] = None
    city_keywords: Optional[List[str]] = None
    plan: Optional[PlanTierEnum] = None
    autoEnabled: Optional[bool] = None

    class Config:
        populate_by_name = True

class UrlsToAnalyze(BaseModel):
    urls: List[HttpUrl]

# =========================================================
# URL Analyzer - Analizador de Percepción Digital
# =========================================================
from typing import Literal

class Politician(BaseModel):
    name: str = Field(..., description="Nombre del personaje")
    office: Optional[str] = Field(None, description="Cargo opcional")

class PostAI(BaseModel):
    summary: str
    topic: Optional[str] = None
    subtopics: List[str] = []
    sentiment: Literal["negative", "neutral", "positive"] = "neutral"
    stance: Literal["against", "neutral", "favor", "none"] = "none"
    entities: List[str] = []
    toxicity: int = 0
    risk_note: Optional[str] = None
    opportunities: List[str] = []

class PostMeta(BaseModel):
    platform: str
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    author_name: Optional[str] = None
    published_at: Optional[str] = None
    thumbnail_url: Optional[str] = None
    debug: Optional[str] = None
    likes: Optional[int] = None
    shares: Optional[int] = None
    comments: Optional[int] = None

class PostResult(BaseModel):
    meta: PostMeta
    ai: PostAI

class AnalyzeURLRequest(BaseModel):
    urls: List[HttpUrl]
    politician: Politician

class AnalyzeURLResponse(BaseModel):
    politician: Politician
    results: List[PostResult]
    summary: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = None

# =========================================================
# Social Monitoring - Monitoreo de Redes Sociales
# =========================================================
from enum import Enum as PyEnum

class SocialPlatformEnum(str, PyEnum):
    FACEBOOK = "facebook"
    TWITTER = "twitter"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"

class MonitoringStatusEnum(str, PyEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    PENDING = "pending"

class RiskLevelEnum(str, PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class MonitoringSourceCreate(BaseModel):
    url: HttpUrl
    platform: SocialPlatformEnum
    name: Optional[str] = None

class MonitoringSourceOut(BaseModel):
    id: str
    campaignId: str
    url: str
    platform: SocialPlatformEnum
    name: Optional[str]
    status: MonitoringStatusEnum
    lastRunAt: Optional[datetime] = None
    lastRunStatus: Optional[str] = None
    lastRunPostsCount: Optional[int] = None
    totalPostsCollected: int = 0
    errorCount: int = 0
    createdAt: datetime

    class Config:
        from_attributes = True

class AnalyticResultOut(BaseModel):
    id: str
    postUrl: Optional[str] = None
    postContent: Optional[str] = None
    postAuthor: Optional[str] = None
    postDate: Optional[datetime] = None
    likes: Optional[int] = None
    shares: Optional[int] = None
    comments: Optional[int] = None
    sentiment: Optional[str] = None
    sentimentScore: Optional[float] = None
    riskLevel: Optional[RiskLevelEnum] = None
    riskScore: Optional[int] = None
    topics: Optional[List[str]] = None
    summary: Optional[str] = None
    requiresAttention: bool = False
    createdAt: datetime

    class Config:
        from_attributes = True
