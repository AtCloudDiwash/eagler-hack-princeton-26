"""Matterport interior adapter (mock: backend/fixtures/observations.json, 'interior' facts)."""
from __future__ import annotations

from typing import Any

from ..models import Property
from ._fixtures import load_fixture


def get_interior(prop: Property) -> dict[str, Any]:
    """Floor plan / 3D tour links plus facts measured from the interior scan."""
    record = load_fixture("observations.json").get(prop.id, {})
    return {
        "floor_plan_url": record.get("floor_plan_url"),
        "matterport_embed_url": prop.matterport_url,
        "observations": record.get("interior", {}),
    }
