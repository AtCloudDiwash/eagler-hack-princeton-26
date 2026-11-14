"""Matterport interior adapter.

Mock mode (default): floor plan URL and interior facts from backend/fixtures/observations.json
('interior' block), served as SVG placeholders from backend/static/floorplans/.

Live mode (USE_MOCK_DATA=false + MATTERPORT_API_KEY): queries the Matterport Model API
(`MATTERPORT_API_BASE_URL`, GraphQL) for the model's floor plan asset. Measurements still come
from the fixtures — automated door/fixture detection is out of scope for the hackathon. Any live
failure falls back to the fixture URL.
"""
from __future__ import annotations

from typing import Any

import httpx

from ..config import log, settings
from ..models import Property
from ._fixtures import load_fixture


def _record(property_id: str) -> dict[str, Any]:
    return load_fixture("observations.json").get(property_id, {})


def _model_id(matterport_url: str | None) -> str | None:
    """'https://my.matterport.com/show/?m=AbC123' -> 'AbC123'."""
    if matterport_url and "m=" in matterport_url:
        return matterport_url.split("m=", 1)[1].split("&", 1)[0]
    return None


def _live_floor_plan_url(model_id: str) -> str | None:
    query = "query($id: ID!) { model(id: $id) { assets { floorplans { url } } } }"
    response = httpx.post(
        settings.matterport_api_base_url,
        json={"query": query, "variables": {"id": model_id}},
        auth=(settings.matterport_api_key or "", ""),
        timeout=settings.provider_timeout_seconds,
    )
    response.raise_for_status()
    plans = response.json()["data"]["model"]["assets"]["floorplans"]
    return plans[0]["url"] if plans else None


def get_interior_images(property_id: str, matterport_url: str | None = None) -> dict[str, str | None]:
    """Floor plan image + 3D tour embed URL for a property (prompt 04 interface)."""
    floor_plan_url = _record(property_id).get("floor_plan_url")
    model_id = _model_id(matterport_url)
    if settings.provider_mode(settings.matterport_api_key) == "live" and model_id:
        try:
            floor_plan_url = _live_floor_plan_url(model_id) or floor_plan_url
        except Exception as exc:  # noqa: BLE001 - fall back to the placeholder image
            log.warning("Matterport live call failed (%s); using fixture floor plan", exc)
    return {"floor_plan_url": floor_plan_url, "matterport_url": matterport_url}


def get_interior(prop: Property) -> dict[str, Any]:
    """Floor plan / 3D tour links plus facts measured from the interior scan."""
    images = get_interior_images(prop.id, prop.matterport_url)
    return {
        "floor_plan_url": images["floor_plan_url"],
        "matterport_embed_url": images["matterport_url"],
        "observations": _record(prop.id).get("interior", {}),
    }
