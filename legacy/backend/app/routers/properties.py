"""GET /api/v1/properties — candidate listings from the CoStar provider (mock fixtures by default)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..config import business_types
from ..models import Property
from ..providers import costar_provider

router = APIRouter(tags=["properties"])


@router.get("/properties", response_model=list[Property])
def list_properties(
    business_type: str | None = Query(None, examples=["restaurant"]),
    city: str | None = Query(None, description="City name or ZIP", examples=["Austin"]),
    state: str | None = Query(None, examples=["TX"]),
    min_size: int | None = Query(None, ge=0, description="Minimum sq ft"),
    max_size: int | None = Query(None, ge=0, description="Maximum sq ft"),
    budget: float | None = Query(None, ge=0, description="Maximum monthly rent (USD)"),
) -> list[Property]:
    if business_type and business_type not in business_types():
        raise HTTPException(400, f"Unknown business type '{business_type}'")
    return costar_provider.search_properties(
        city=city, state=state, min_size=min_size, max_size=max_size, max_rent=budget
    )
