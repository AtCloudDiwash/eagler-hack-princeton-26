"""GET /api/v1/business-types — options for the profile form (config/business_types.yaml)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import business_types

router = APIRouter(tags=["config"])


class BusinessTypeOut(BaseModel):
    id: str
    label: str
    capacity_unit: str
    default_capacity: int
    needs_kitchen: bool


@router.get("/business-types", response_model=list[BusinessTypeOut])
def list_business_types() -> list[BusinessTypeOut]:
    return [
        BusinessTypeOut(
            id=type_id,
            label=cfg.get("label", type_id),
            capacity_unit=cfg.get("capacity_unit", "units"),
            default_capacity=int(cfg.get("default_capacity", 1)),
            needs_kitchen=bool(cfg.get("needs_kitchen", False)),
        )
        for type_id, cfg in business_types().items()
    ]
