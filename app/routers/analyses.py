from __future__ import annotations
from fastapi import APIRouter

# Intentionally no prefix here; main mounts with prefix="/analyses"
router = APIRouter(tags=["analyses"])

# The /ingest endpoint that was here is now obsolete.
# The new process is triggered from the campaign creation and refresh endpoints.
