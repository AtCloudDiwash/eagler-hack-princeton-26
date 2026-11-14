"""Vexcel aerial imagery adapter (mock: backend/fixtures/observations.json, 'aerial' facts)."""
from __future__ import annotations

from typing import Any

from ..models import Property
from ._fixtures import load_fixture


def get_aerial(prop: Property) -> dict[str, Any]:
    """Aerial image link plus facts read from overhead imagery (parking, rooftop units)."""
    record = load_fixture("observations.json").get(prop.id, {})
    return {
        "aerial_url": record.get("aerial_url"),
        "observations": record.get("aerial", {}),
    }
