"""CoStar listings adapter.

Mock mode (default) reads backend/fixtures/properties.json. Live mode is enabled when
USE_MOCK_DATA=false and COSTAR_API_KEY is set: it calls `COSTAR_API_BASE_URL/listings` (a
placeholder endpoint — swap in the real path/params from your CoStar developer docs) and maps the
response with `map_costar_listing`. Any failure (network, auth, unexpected shape) falls back to
the fixtures so the demo never breaks.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import log, settings
from ..models import Property
from ._fixtures import load_fixture


def _fixture_properties() -> list[Property]:
    return [Property(**row) for row in load_fixture("properties.json")]


def _first(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        node: Any = row
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        # Skip empty and container values (e.g. "address" may be a nested object in CoStar payloads).
        if node not in (None, "") and not isinstance(node, (dict, list)):
            return node
    return default


def map_costar_listing(row: dict[str, Any]) -> Property:
    """Map a CoStar-style listing record onto our Property model (tolerant of field naming)."""
    return Property(
        id=str(_first(row, "id", "listingId", "propertyId")),
        address=_first(row, "address", "address.streetAddress", "streetAddress", default=""),
        city=_first(row, "city", "address.city", default=""),
        state=_first(row, "state", "address.state", "address.stateCode", default=""),
        zip=str(_first(row, "zip", "postalCode", "address.postalCode", default="")),
        size_sqft=int(_first(row, "size_sqft", "availableSpaceSf", "rentableBuildingArea", "squareFeet", default=0)),
        rent=float(_first(row, "rent", "monthlyRent", default=0) or 0),
        zoning=_first(row, "zoning", "zoningCode"),
        previous_use=_first(row, "previous_use", "previousUse", "propertyType"),
        ti_allowance_per_sqft=_first(row, "ti_allowance_per_sqft", "tiAllowancePerSf"),
        latitude=_first(row, "latitude", "location.latitude"),
        longitude=_first(row, "longitude", "location.longitude"),
        image_url=_first(row, "image_url", "primaryPhotoUrl"),
        matterport_url=_first(row, "matterport_url", "virtualTourUrl"),
        available=bool(_first(row, "available", "isAvailable", default=True)),
    )


def _live_properties() -> list[Property]:
    response = httpx.get(
        f"{settings.costar_api_base_url}/listings",
        headers={"Authorization": f"Bearer {settings.costar_api_key}", "Accept": "application/json"},
        params={"propertyType": "retail", "listingType": "lease"},
        timeout=settings.provider_timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("listings", payload) if isinstance(payload, dict) else payload
    properties = [map_costar_listing(row) for row in rows]
    if not properties:
        raise ValueError("CoStar returned no listings")
    return properties


def all_properties() -> list[Property]:
    if settings.provider_mode(settings.costar_api_key) == "live":
        try:
            return _live_properties()
        except Exception as exc:  # noqa: BLE001 - any provider failure falls back to mock data
            log.warning("CoStar live call failed (%s); using fixtures", exc)
    return _fixture_properties()


def search_properties(
    city: str | None = None,
    state: str | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    max_rent: float | None = None,
) -> list[Property]:
    """Filter listings by location (city name or ZIP), size and rent. All filters are optional."""
    results = []
    for prop in all_properties():
        if not prop.available:
            continue
        if city and prop.city.lower() != city.strip().lower() and prop.zip != city.strip():
            continue
        if state and prop.state.lower() != state.strip().lower():
            continue
        if min_size and prop.size_sqft < min_size:
            continue
        if max_size and prop.size_sqft > max_size:
            continue
        if max_rent and prop.rent > max_rent:
            continue
        results.append(prop)
    return results


def get_property(property_id: str) -> Property | None:
    return next((p for p in all_properties() if p.id == property_id), None)
