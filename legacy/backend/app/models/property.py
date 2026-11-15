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
    # Recorded deed / lease / shopping-center use restrictions disclosed with the listing, as tags
    # (e.g. "no_food_service"). None = the listing says nothing; [] = the listing discloses none.
    # jurisdictions.yaml `use_restriction_blocks` maps tags to the business uses they prohibit.
    use_restrictions: list[str] | None = None
    # Where the listing record came from: "costar" (live API) or "sample" (hand-made demo fixture
    # at a real address; rent, size, previous use and TI are illustrative, not market data).
    listing_source: str | None = None
