"""Vexcel aerial imagery adapter.

Mock mode (default): aerial URL and overhead facts (parking count, rooftop units) from
backend/fixtures/observations.json ('aerial' block), served as SVG placeholders from
backend/static/aerials/.

Live mode (USE_MOCK_DATA=false + VEXCEL_API_KEY): requests an orthophoto for the property's
coordinates from `VEXCEL_API_BASE_URL` (placeholder path — use the endpoint from your Vexcel
account docs). Parking / HVAC counts still come from the fixtures. Any failure falls back to the
fixture image.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import log, settings
from ..models import Property
from ._fixtures import load_fixture


def _record(property_id: str) -> dict[str, Any]:
    return load_fixture("observations.json").get(property_id, {})


def _live_aerial_url(latitude: float, longitude: float) -> str | None:
    response = httpx.get(
        f"{settings.vexcel_api_base_url}/images/ortho",
        params={"lat": latitude, "lon": longitude, "zoom": 20, "format": "json"},
        headers={"Authorization": f"Bearer {settings.vexcel_api_key}"},
        timeout=settings.provider_timeout_seconds,
    )
    response.raise_for_status()
    return response.json().get("url")


def get_aerial_image(prop: Property) -> dict[str, str | None]:
    """Aerial image URL for a property (prompt 04 interface)."""
    aerial_url = _record(prop.id).get("aerial_url")
    if (
        settings.provider_mode(settings.vexcel_api_key) == "live"
        and prop.latitude is not None
        and prop.longitude is not None
    ):
        try:
            aerial_url = _live_aerial_url(prop.latitude, prop.longitude) or aerial_url
        except Exception as exc:  # noqa: BLE001 - fall back to the placeholder image
            log.warning("Vexcel live call failed (%s); using fixture aerial", exc)
    return {"aerial_url": aerial_url}


def get_aerial(prop: Property) -> dict[str, Any]:
    """Aerial image link plus facts read from overhead imagery (parking, rooftop units)."""
    return {
        "aerial_url": get_aerial_image(prop)["aerial_url"],
        "observations": _record(prop.id).get("aerial", {}),
    }
