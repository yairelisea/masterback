from __future__ import annotations
from fastapi import APIRouter

# Endpoints moved to app.routers.campaigns to avoid duplication
router = APIRouter(prefix="", tags=["items"])  # kept for compatibility; no routes defined here
