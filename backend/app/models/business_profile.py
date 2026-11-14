from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BusinessProfile(BaseModel):
    """What the user typed: a business type plus free-text requirements."""

    type: str = Field(..., min_length=1, examples=["restaurant"])
    details: str = Field("", examples=["40 seats, kitchen needed, 2 bathrooms, 20 parking spaces"])
    city: str = Field(..., min_length=1, examples=["Austin"])
    state: str = Field(..., min_length=2, examples=["TX"])


class Requirements(BaseModel):
    """Structured needs produced by the requirements parser agent."""

    business_type: str
    business_label: str
    city: str
    state: str
    capacity: int = Field(..., description="Seats for a restaurant, chairs for a clinic, ...")
    capacity_unit: str
    occupant_load: int
    parking_required: int
    parking_source: Literal["user", "guideline"] = Field(..., description="'user' if stated, otherwise 'guideline'")
    bathrooms_required: int
    min_sqft: int | None = None
    max_sqft: int | None = None
    max_rent: float | None = None
    needs_kitchen: bool = False
    required_hvac_tons: float
    required_electrical_amps: int
    assumptions: list[str] = Field(default_factory=list)
