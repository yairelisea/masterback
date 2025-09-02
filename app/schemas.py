from pydantic import BaseModel, Field, AnyUrl, EmailStr
from typing import Optional, List, Any, Literal
from datetime import datetime

SourceTypeLiteral = Literal["NEWS","FACEBOOK","INSTAGRAM","X","YOUTUBE","TIKTOK"]

class CampaignCreate(BaseModel):
    name: str
    slug: str
    description: Optional[str] = None
    ownerEmail: EmailStr = "admin@bbx.local"

class SourceCreate(BaseModel):
    type: SourceTypeLiteral
    url: AnyUrl
    label: Optional[str] = None

class IngestCreate(BaseModel):
    campaignId: str
    sourceType: SourceTypeLiteral
    sourceUrl: AnyUrl
    contentUrl: AnyUrl
    author: Optional[str] = None
    title: Optional[str] = None
    excerpt: Optional[str] = None
    publishedAt: Optional[datetime] = None

class AnalyzeCreate(BaseModel):
    campaignId: str
    itemId: Optional[str] = None
    model: str = "gpt-5"
    summary: Optional[str] = None
    sentiment: Optional[float] = Field(default=None, ge=-1, le=1)
    stance: Optional[str] = None
    topics: Optional[List[Any]] = None
    entities: Optional[Any] = None
    score: Optional[float] = None