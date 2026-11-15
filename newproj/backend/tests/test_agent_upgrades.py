"""Cost / Compliance / Vexcel agent upgrades: flood zone, prior use (second generation), data-quality flags."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

from agents.base import EvidenceStore, RunContext, ToolBudget  # noqa: E402
from schemas import AgentMetricAssessment, AgentReport  # noqa: E402
from services import rules  # noqa: E402


def _ctx(places=None, places_ok=True, business_type="restaurant") -> RunContext:
    _, jur = rules.jurisdiction_for("Houston", "Texas")
    fp = {"type": "Polygon", "coordinates": [[[-95.3601, 29.7599], [-95.3599, 29.7599], [-95.3599, 29.7601], [-95.3601, 29.7601], [-95.3601, 29.7599]]]}
    return RunContext(
        query="40-seat restaurant in Houston", intent={"business_type": business_type, "requirements": []},
        property={"id": "p", "lat": 29.76, "lon": -95.36, "footprint": fp}, feature=None,
        neighborhood={"places": places or [], "sources": [{"name": "OpenStreetMap places (Overpass)", "status": "used" if places_ok else "unavailable", "note": ""}]},
        neighbor_features=[], census={}, jurisdiction_key="houston-tx", jurisdiction=jur, target_sqft=1400, target_basis="test",
        extra_requirements=None, evidence=EvidenceStore(), emit=lambda *a, **k: None,
    )


def test_flood_item_maps_fema_zones_to_rule_statuses():
    _, jur = rules.jurisdiction_for("Houston", "Texas")
    sfha = rules.flood_item(jur, {"status": "ok", "zone": "AE", "subtype": None, "sfha": True, "moderate": False})
    assert sfha["status"] == "risk" and sfha["level"] == "sfha" and "Ch. 19" in sfha["citation"]
    minimal = rules.flood_item(jur, {"status": "ok", "zone": "X", "subtype": "AREA OF MINIMAL FLOOD HAZARD", "sfha": False, "moderate": False})
    assert minimal["status"] == "pass" and minimal["level"] == "minimal"
    assert rules.flood_item(jur, {"status": "unknown", "error": "down"})["status"] == "unknown"  # never "no risk" on failure


def test_flood_lookup_failure_is_unknown(monkeypatch):
    import httpx

    from services import flood

    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(flood.httpx, "get", boom)
    out = flood.flood_zone(10.0001, 10.0001)
    assert out["status"] == "unknown" and "unavailable" in out["error"]


def test_engine_flood_rule_governs_the_metric():
    from multi_agent_engine import EventLog, merge_metrics

    ctx = _ctx()
    eid = ctx.evidence.add("compliance", "check_flood_zone", "FEMA", "AE", {"id": "flood_zone", "rule": "Flood", "status": "risk", "level": "sfha", "detail": "AE", "evidence": {"zone": "AE"}})
    rep = AgentReport(agent="compliance", label="Compliance Agent", status="completed",
                      metric_assessments=[AgentMetricAssessment(metric_id="flood_risk", status="strong", rationale="looks fine", evidence_ids=[eid])])
    log = EventLog.__new__(EventLog)
    log.emit = lambda *a, **k: None  # type: ignore[method-assign]
    metrics, conflicts = merge_metrics(ctx, {"compliance": rep}, log)
    assert next(m for m in metrics if m.id == "flood_risk").status == "weak" and conflicts


def test_prior_use_marks_second_generation_and_drops_kitchen_items():
    from agents.cost_agent import build_tools, pick_adders, prior_use

    deli = {"name": "Jason's Deli", "category": "amenity=restaurant", "group": "food_drink", "lat": 29.76, "lon": -95.36, "distance_m": 3}
    far = {"name": "Far Cafe", "category": "amenity=cafe", "group": "food_drink", "lat": 29.762, "lon": -95.36, "distance_m": 220}
    ctx = _ctx(places=[deli, far])
    assert [p["name"] for p in prior_use(ctx)] == ["Jason's Deli"]
    tools = {t.name: t for t in build_tools(ctx, ToolBudget(5))}
    out = json.loads(tools["check_prior_use"].invoke({}))
    assert out["data"]["second_generation_likely"] is True
    ids = {a["id"] for a in pick_adders(ctx)}
    assert "hood_exhaust" not in ids and "grease_interceptor" not in ids

    fresh = _ctx(places=[far])
    assert prior_use(fresh) == [] and "hood_exhaust" in {a["id"] for a in pick_adders(fresh)}
    assert prior_use(_ctx(places=[deli], places_ok=False)) is None  # unknown, not "no prior use"


def test_vexcel_data_quality_flags():
    from agents.vexcel_agent import building_flags, paving_flags

    flags = building_flags({"building-type.class": "commercial", "building-type.score": 0.41, "footprint.area": 560})
    assert len(flags) == 3  # low confidence, tiny footprint, no height
    assert building_flags({"building-type.score": 0.95, "footprint.area": 3000, "roof-characteristics.height": 28.0}) == []
    assert paving_flags({"hardscapes.area": 233, "vehicles.count": 21}) and not paving_flags({"hardscapes.area": 9000, "vehicles.count": 21})
