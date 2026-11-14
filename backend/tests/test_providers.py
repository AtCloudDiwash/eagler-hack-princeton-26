"""Providers: mock mode by default, live mode falls back to fixtures on any failure."""
from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.providers import costar_provider, matterport_provider, vexcel_provider
from app.services.agent_orchestrator import gather_observations


def test_mock_mode_is_default():
    assert settings.mode_summary == {"costar": "mock", "matterport": "mock", "vexcel": "mock"}
    assert len(costar_provider.all_properties()) == 4


def test_mock_interior_and_aerial():
    prop = costar_provider.get_property("property-456")
    interior = matterport_provider.get_interior(prop)
    assert interior["floor_plan_url"] == "/static/floorplans/property-456.svg"
    assert interior["observations"]["kitchen_equipment_visible"]["value"] is True
    assert matterport_provider.get_interior_images("property-456") == {
        "floor_plan_url": "/static/floorplans/property-456.svg", "matterport_url": None,
    }
    assert vexcel_provider.get_aerial_image(prop) == {"aerial_url": "/static/aerials/property-456.svg"}
    assert vexcel_provider.get_aerial(prop)["observations"]["visible_parking_count"]["value"] == 22


def test_vision_agent_merges_sources():
    observations, media = gather_observations(costar_provider.get_property("property-123"))
    assert observations["zoning_code"].source == "costar" and observations["zoning_code"].value == "CS-MU"
    assert observations["door_width_inches"].source == "matterport"
    assert observations["visible_parking_count"].source == "vexcel"
    assert observations["visible_parking_count"].box == [0.05, 0.6, 0.55, 0.3]
    assert media.aerial_url.endswith("property-123.svg") and media.image_url.endswith("property-123.svg")


@pytest.fixture
def live_mode(monkeypatch):
    monkeypatch.setattr(settings, "force_mock", False)
    for key in ("costar_api_key", "matterport_api_key", "vexcel_api_key"):
        monkeypatch.setattr(settings, key, "test-key")

    def no_network(*args, **kwargs):
        raise httpx.ConnectError("network disabled in tests")

    monkeypatch.setattr(httpx, "get", no_network)
    monkeypatch.setattr(httpx, "post", no_network)


def test_live_failures_fall_back_to_fixtures(live_mode):
    assert settings.mode_summary["costar"] == "live"
    props = costar_provider.all_properties()
    assert len(props) == 4
    prop = props[0]
    assert vexcel_provider.get_aerial_image(prop)["aerial_url"].startswith("/static/aerials/")
    images = matterport_provider.get_interior_images(prop.id, "https://my.matterport.com/show/?m=AbC123")
    assert images["floor_plan_url"].startswith("/static/floorplans/")


def test_live_costar_maps_listings(live_mode, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"listings": [{
                "listingId": 77, "address": {"streetAddress": "1 Live St", "city": "Austin", "state": "TX", "postalCode": "78701"},
                "availableSpaceSf": 2100, "monthlyRent": 5100, "zoningCode": "CS",
            }]}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse())
    props = costar_provider.all_properties()
    assert props[0].id == "77" and props[0].address == "1 Live St" and props[0].size_sqft == 2100 and props[0].zoning == "CS"
