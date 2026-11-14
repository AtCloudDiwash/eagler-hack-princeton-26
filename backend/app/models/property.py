from __future__ import annotations

from pydantic import BaseModel


class Property(BaseModel):
    """A listing as returned by the CoStar provider."""

    id: str
    address: str
    city: str
    state: str
    zip: str
    size_sqft: int
    rent: float  # monthly
    zoning: str | None = None
    previous_use: str | None = None
    ti_allowance_per_sqft: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    image_url: str | None = None
    matterport_url: str | None = None
    available: bool = True
