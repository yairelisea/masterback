# app/schemas/search_local.py
from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from datetime import datetime

class LocalArticleCreate(BaseModel):
    campaign_id: Optional[str] = None
    query: str
    source_name: Optional[str] = None
    source_domain: Optional[str] = None
    title: str
    url: HttpUrl
    published_at: Optional[datetime] = None
    location: Optional[str] = None

class LocalArticleOut(LocalArticleCreate):
    id: int

class RunSearchIn(BaseModel):
    query: str
    campaign_id: Optional[str] = None
    location: Optional[str] = None
    limit: int = 35

class RunSearchOut(BaseModel):
    inserted: int
    skipped: int
    items: List[LocalArticleOut]
