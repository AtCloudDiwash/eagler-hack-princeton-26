"""POST /api/v1/analyze — run the agent pipeline, store the run in SQLite, return it."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import db
from ..models import AnalyzeRequest, AnalyzeResponse
from ..providers import costar_provider
from ..services.agent_orchestrator import analyze_properties
from ..services.requirements_parser import UnknownBusinessType, get_business

router = APIRouter(tags=["analysis"])


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        get_business(request.business_profile.type)
    except UnknownBusinessType as exc:
        raise HTTPException(400, str(exc)) from exc

    property_ids = list(dict.fromkeys(pid.strip() for pid in request.property_ids if pid.strip()))
    if not property_ids:
        raise HTTPException(422, "property_ids must contain at least one property id")
    properties = []
    for pid in property_ids:
        prop = costar_provider.get_property(pid)
        if prop is None:
            raise HTTPException(404, f"Unknown property id '{pid}'")
        properties.append(prop)

    response = analyze_properties(request.business_profile, properties)
    db.save_run(response)
    return response
