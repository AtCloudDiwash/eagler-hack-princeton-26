"""GET /health — liveness plus which providers / parser are active."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": {**settings.mode_summary, "parser": settings.parser_mode}}
