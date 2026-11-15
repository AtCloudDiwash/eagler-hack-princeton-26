"""Regression coverage for effects promised by conversational discovery."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

from schemas import Budget, Intent, Need
from services import discovery


def test_budget_ranks_affordable_suite_above_expensive_suite():
    intent = Intent(sqft=1800, budget=Budget(amount=8000, period="monthly"))
    candidate = {"building_type": "commercial", "distance_m": 200, "address": "100 Main St, Houston, TX",
                 "best_space": {"sqft": 1800, "suite": "100", "floor": "1", "ground_floor": True, "service": "TripleNet"}}
    affordable = {**candidate, "best_space": {**candidate["best_space"], "rent_per_sqft_yr": 10}}
    expensive = {**candidate, "best_space": {**candidate["best_space"], "rent_per_sqft_yr": 200}}
    low, reasons = discovery.prescreen(affordable, intent)
    high, _ = discovery.prescreen(expensive, intent)
    assert low > high
    assert any("Budget (planning estimate)" in r for r in reasons)


def test_near_changes_search_center_and_ground_only_excludes_unknowns(monkeypatch):
    from config import settings
    calls = []
    async def locate(text, notes):
        return {"lat": 40.0, "lon": -74.0, "name": "Town"}
    async def geocode(text):
        calls.append(text)
        return {"lat": 40.01, "lon": -74.01, "name": "Rice"}
    async def buildings(lat, lon):
        calls.append((lat, lon))
        return [
            {"id": "confirmed", "lat": lat, "lon": lon, "building_type": "commercial", "source": "osm",
             "best_space": {"suite": "100", "floor": "1", "sqft": 1800, "ground_floor": True}},
            {"id": "unknown", "lat": lat, "lon": lon, "building_type": "commercial", "source": "osm"},
            {"id": "upper", "lat": lat, "lon": lon, "building_type": "commercial", "source": "osm",
             "best_space": {"suite": "200", "sqft": 1800, "floor": "2", "ground_floor": False}},
        ]
    monkeypatch.setattr(discovery, "locate", locate)
    monkeypatch.setattr(discovery.external, "geocode", geocode)
    monkeypatch.setattr(discovery, "_osm_buildings", buildings)
    monkeypatch.setattr(discovery, "attach_costar", lambda *a: set())
    monkeypatch.setattr(discovery.costar, "available", lambda: False)
    monkeypatch.setattr(discovery.db, "get_property", lambda *a: None)
    monkeypatch.setattr(discovery.db, "save_property", lambda *a: None)
    monkeypatch.setattr(settings, "vexcel_api_key", "")
    intent = Intent(location_text="Town", near=["Rice"], needs=[Need(id="ground_floor", label="Ground floor", priority="must")],
                    requirements=["outdoor music allowed"])
    result = asyncio.run(discovery.search("", intent))
    assert calls == ["Rice, Town", (40.01, -74.01)]
    assert [c.id for c in result.candidates] == ["confirmed"]
    assert any("1 building(s) with unconfirmed floor" in note for note in result.notes)
    assert any("not used to rank discovery" in note for note in result.notes)


def test_only_ground_floor_is_a_hard_need_in_rules():
    from services.intent import parse_rules
    for message in ("only ground floor", "ground floor only"):
        need = next(n for n in parse_rules(message).needs if n.id == "ground_floor")
        assert need.priority == "must"
