"""GET /health — liveness plus which providers / parser / LLM are active."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import settings
from ..services import llm

router = APIRouter(tags=["health"])


def llm_mode() -> dict[str, str]:
    """Configured parser + LLM, or regex / none when the LLM isn't reachable right now."""
    if llm.is_available():
        return {"parser": llm.parser_name(), "llm": llm.label()}
    return {"parser": "regex", "llm": "none"}


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "mode": {**settings.mode_summary, **llm_mode()}}
