"""GET /api/v1/analyses (history) and GET /api/v1/analyses/{id} (stored AnalyzeResponse)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from .. import db
from ..models import AnalysisSummary

router = APIRouter(tags=["analysis"])


@router.get("/analyses", response_model=list[AnalysisSummary])
def list_analyses(limit: int = Query(20, ge=1, le=100)) -> list[AnalysisSummary]:
    return db.list_runs(limit)


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> JSONResponse:
    stored = db.get_run(analysis_id)
    if stored is None:
        raise HTTPException(404, f"Unknown analysis id '{analysis_id}'")
    # Returned verbatim: exactly what POST /api/v1/analyze returned.
    return JSONResponse(stored)
