# app/schemas.py
from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


# =========================================================
# Campaign schemas
# =========================================================
class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    query: str = Field(..., min_length=1, max_length=300)
    size: int = 25
    days_back: int = Field(14, alias="days_back")
    lang: str = "es-419"
    country: str = "MX"
    city_keywords: Optional[List[str]] = None

    class Config:
        populate_by_name = True  # acepta "days_back" o "daysBack"


class CampaignOut(BaseModel):
    id: str
    name: str
    query: str
    size: int
    days_back: int
    lang: str
    country: str
    city_keywords: Optional[List[str]] = None
    userId: Optional[str] = None
    createdAt: Optional[datetime] = None

    class Config:
        from_attributes = True


# =========================================================
# Source schemas
# =========================================================
class SourceTypeEnum(str, Enum):
    NEWS = "NEWS"
    RSS = "RSS"
    TWITTER = "TWITTER"
    OTHER = "OTHER"


class SourceCreate(BaseModel):
    """
    Body para crear un SourceLink.  Debe mapear con app.models.SourceLink:
    - type: uno de NEWS/RSS/TWITTER/OTHER
    - url: la URL de la fuente
    - campaignId: opcional; si no viene, el endpoint puede inferirlo/validarlo
    """
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