"""GET /api/v1/analyses (history) and GET /api/v1/analyses/{id} (stored AnalyzeResponse)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .. import db
from ..models import AnalysisSummary, AnalyzeResponse

router = APIRouter(tags=["analysis"])


@router.get("/analyses", response_model=list[AnalysisSummary])
def list_analyses(limit: int = Query(20, ge=1, le=100)) -> list[AnalysisSummary]:
    return db.list_runs(limit)


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> JSONResponse:
    stored = db.get_run(analysis_id)
    if stored is None:
        raise HTTPException(404, f"Unknown analysis id '{analysis_id}'")
    return JSONResponse(_with_defaults(stored))


def _with_defaults(stored: dict[str, Any]) -> dict[str, Any]:
    """Exactly what POST /api/v1/analyze returned, plus defaults for fields added since the run was
    stored (e.g. `min_score` = 0 and `weak_fit` = false for runs ranked before the min-score gate).
    Falls back to the stored JSON verbatim if it no longer validates against the current model."""
    try:
        return AnalyzeResponse.model_validate(stored).model_dump(mode="json")
    except ValidationError:
        return stored
