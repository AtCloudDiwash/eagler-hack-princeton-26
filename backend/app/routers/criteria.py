"""GET /api/v1/criteria — the criteria registry, optionally filtered by business type / jurisdiction."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..config import business_types
from ..models import Criterion
from ..services.criteria_manager import applicable_criteria

router = APIRouter(tags=["config"])


@router.get("/criteria", response_model=list[Criterion])
def list_criteria(
    business_type: str | None = Query(None, examples=["restaurant"]),
    city: str | None = Query(None, examples=["Austin"]),
    state: str | None = Query(None, examples=["TX"]),
) -> list[Criterion]:
    if business_type and business_type not in business_types():
        raise HTTPException(400, f"Unknown business type '{business_type}'")
    return applicable_criteria(business_type, city, state)
