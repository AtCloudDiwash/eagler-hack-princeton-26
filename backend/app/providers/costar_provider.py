"""CoStar listings adapter.

Mock mode (default) reads backend/fixtures/properties.json. Live mode is enabled when
USE_MOCK_DATA=false and COSTAR_API_KEY is set; the live call is wired up in phase 04
(prompts/04-integrations.md) and any failure falls back to the fixtures.
"""
from __future__ import annotations

from ..config import log, settings
from ..models import Property
from ._fixtures import load_fixture


def _fixture_properties() -> list[Property]:
    return [Property(**row) for row in load_fixture("properties.json")]


def _live_properties() -> list[Property]:
    raise NotImplementedError("CoStar live API is added in phase 04")


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
    """Filter listings by location, size and rent. All filters are optional."""
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
