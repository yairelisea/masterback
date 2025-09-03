# app/schemas.py
from __future__ import annotations
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field

# -------- Campaign --------
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
    city_keywords: Optional[list[str]] = None
    userId: Optional[str] = None
    createdAt: Optional[datetime] = None

    class Config:
        from_attributes = True  # permite .from_orm()