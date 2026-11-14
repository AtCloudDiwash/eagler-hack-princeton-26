"""Unit tests for the deterministic parts: scoring, cost engine, rules, geometry, intent rules and the
engine's validation precedence. (Agent/LLM behaviour is exercised by the end-to-end run, not here.)"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

from langchain_core.messages import AIMessage  # noqa: E402

from agents.base import EvidenceStore, RunContext, _parse_text_report  # noqa: E402
from config import business_types, metrics_registry  # noqa: E402
from schemas import AgentMetricAssessment, AgentReport  # noqa: E402
from services import costs, rules, scoring  # noqa: E402
from services.geo import parse_wkt, point_in_polygon  # noqa: E402
from services.intent import parse_rules, target_sqft  # noqa: E402


def test_every_business_metric_exists_in_registry():
    reg = metrics_registry()
    for key, cfg in business_types().items():
        assert set(cfg["metrics"]) <= set(reg), key
        for m in cfg["metrics"].values():
            assert m["weight"] >= 0 and m["why"]


def test_scoring_blocker_forces_not_recommended():
    rows = [
        {"id": "permitted_use", "weight": 14, "status": "blocker", "score": 0.0, "evidence_ids": ["E1"], "hard_block": True},
        {"id": "size_fit", "weight": 10, "status": "strong", "score": 100.0, "evidence_ids": ["E2"], "hard_block": False},
    ]
    assert scoring.overall(rows)["verdict"] == "not_recommended"


def test_scoring_low_confidence_is_insufficient_evidence():
    rows = [
        {"id": "a", "weight": 10, "status": "strong", "score": 100.0, "evidence_ids": ["E1"], "hard_block": False},
        {"id": "b", "weight": 30, "status": "unknown", "score": None, "evidence_ids": [], "hard_block": False},
    ]
    out = scoring.overall(rows)
    assert out["confidence"] == 25 and out["verdict"] == "insufficient_evidence"


def test_unverified_claims_pulled_toward_neutral():
    assert scoring.metric_score("strong", True) == 100
    assert scoring.metric_score("strong", False) == 80
    assert scoring.metric_score("unknown", True) is None


def test_cost_engine_is_deterministic_and_rejects_foreign_adders():
    adders = [{"id": "hood_exhaust", "quantity": 1, "reason": "no hood", "evidence_ids": ["E3"]}, {"id": "locker_showers", "quantity": 1}]
    a = costs.estimate("restaurant", 1400, "houston-tx", adders)
    b = costs.estimate("restaurant", 1400, "houston-tx", adders)
    assert a == b
    ids = [l["id"] for l in a["fitout"]["line_items"]]
    assert "hood_exhaust" in ids and "locker_showers" not in ids
    assert a["upfront"]["low"] < a["upfront"]["high"]
    assert a["rent"]["per_sqft_low"] == 22


def test_houston_permitted_use_and_parking():
    key, jur = rules.jurisdiction_for("Houston", "Texas")
    assert key == "houston-tx"
    assert rules.permitted_use(jur, "restaurant")["status"] == "pass"
    # Outside exempt areas: 1,400 sq ft restaurant needs 14 spaces at 10/1,000.
    p = rules.parking_requirement(jur, "restaurant", 1400, 29.80, -95.40, 3250)
    assert p["evidence"]["required_spaces"] == 14 and p["evidence"]["estimated_onsite_spaces"] == 10 and p["status"] == "risk"
    # Downtown market-based area: no minimum.
    assert rules.parking_requirement(jur, "restaurant", 1400, 29.757, -95.365, 0)["status"] == "pass"


def test_unverified_city_is_unknown_never_pass():
    key, jur = rules.jurisdiction_for("Princeton", "New Jersey")
    assert key == "_default"
    assert rules.permitted_use(jur, "gym")["status"] == "unknown"
    assert rules.parking_requirement(jur, "gym", 5000, 40.35, -74.66, 9000)["status"] == "unknown"


def test_parse_wkt_polygon_and_multipolygon():
    poly = parse_wkt("POLYGON ((0 0, 1 0, 1 1, 0 0))")
    assert poly["type"] == "Polygon" and poly["coordinates"][0][1] == [1.0, 0.0]
    multi = parse_wkt("MULTIPOLYGON (((0 0, 1 0, 1 1, 0 0)), ((5 5, 6 5, 6 6, 5 5)))")
    assert multi["type"] == "MultiPolygon" and len(multi["coordinates"]) == 2
    assert point_in_polygon(0.7, 0.2, poly["coordinates"][0])


def test_intent_rules():
    i = parse_rules("I want to open a 40-seat restaurant in Houston.")
    assert (i.business_type, i.seats, i.location_text) == ("restaurant", 40, "Houston")
    assert target_sqft(i)[0] == 40 * 35
    d = parse_rules("I need a commercial property for a dental clinic near Midtown Houston with parking")
    assert d.business_type == "dental_clinic" and "parking" in d.requirements


def test_parse_text_report_accepts_json_text():
    msg = AIMessage(content='```json\n{"summary": "ok", "metric_assessments": [{"metric_id": "size_fit", "status": "strong", "rationale": "fits", "evidence_ids": ["E1"]}]}\n```')
    out = _parse_text_report([msg])
    assert out and out.metric_assessments[0].status == "strong"


def _ctx() -> RunContext:
    _, jur = rules.jurisdiction_for("Houston", "Texas")
    return RunContext(
        query="40-seat restaurant in Houston", intent={"business_type": "restaurant", "requirements": []},
        property={"id": "p", "lat": 29.8, "lon": -95.4}, feature=None, neighborhood={}, neighbor_features=[], census={},
        jurisdiction_key="houston-tx", jurisdiction=jur, target_sqft=1400, target_basis="test", extra_requirements=None,
        evidence=EvidenceStore(), emit=lambda *a, **k: None,
    )


def test_engine_rules_take_precedence_over_agents():
    from multi_agent_engine import EventLog, merge_metrics

    ctx = _ctx()
    eid = ctx.evidence.add("compliance", "check_permitted_use", "x", "unknown", {"status": "unknown", "id": "permitted_use", "rule": "r", "detail": "d"})
    rep = AgentReport(agent="compliance", label="Compliance Agent", status="completed", metric_assessments=[
        AgentMetricAssessment(metric_id="permitted_use", status="strong", rationale="I think it's fine", evidence_ids=[eid]),
    ])
    log = EventLog.__new__(EventLog)
    log.emit = lambda *a, **k: None  # type: ignore[method-assign]
    metrics, conflicts = merge_metrics(ctx, {"compliance": rep}, log)
    pu = next(m for m in metrics if m.id == "permitted_use")
    assert pu.status == "unknown"  # agent cannot claim permitted without verified evidence
    assert conflicts


def test_not_detected_is_never_a_blocker():
    from multi_agent_engine import EventLog, merge_metrics

    ctx = _ctx()
    rep = AgentReport(agent="vexcel", label="Vexcel Agent", status="completed", metric_assessments=[
        AgentMetricAssessment(metric_id="hvac_ventilation", status="blocker", rationale="no AC units detected", evidence_ids=[]),
    ])
    log = EventLog.__new__(EventLog)
    log.emit = lambda *a, **k: None  # type: ignore[method-assign]
    metrics, _ = merge_metrics(ctx, {"vexcel": rep}, log)
    assert next(m for m in metrics if m.id == "hvac_ventilation").status == "weak"


def test_missing_place_data_is_unknown_not_zero():
    import json

    from agents.base import ToolBudget
    from agents.neighborhood_agent import build_tools
    from multi_agent_engine import EventLog, merge_metrics

    ctx = _ctx()
    ctx.neighborhood = {"places": [], "sources": [{"name": "OpenStreetMap places (Overpass)", "status": "unavailable", "note": "502"}]}
    tools = {t.name: t for t in build_tools(ctx, ToolBudget(5))}
    out = json.loads(tools["count_places"].invoke({"group": "food_drink", "radius_m": 500}))
    assert "UNAVAILABLE" in out["summary"] and "data" not in out
    rep = AgentReport(agent="neighborhood", label="Neighborhood Agent", status="completed", metric_assessments=[
        AgentMetricAssessment(metric_id="competition", status="strong", rationale="no competitors found", evidence_ids=["E1"]),
    ])
    log = EventLog.__new__(EventLog)
    log.emit = lambda *a, **k: None  # type: ignore[method-assign]
    metrics, conflicts = merge_metrics(ctx, {"neighborhood": rep}, log)
    assert next(m for m in metrics if m.id == "competition").status == "unknown" and conflicts


def test_cost_tool_drops_invented_evidence_ids():
    import json

    from agents.base import ToolBudget
    from agents.cost_agent import build_tools

    ctx = _ctx()
    real = ctx.evidence.add("vexcel", "inspect_roof", "x", "0 AC units detected", {})
    tools = {t.name: t for t in build_tools(ctx, ToolBudget(5))}
    out = json.loads(tools["estimate_costs"].invoke({"leased_sqft": 1400, "adders": [
        {"id": "hvac_rtu", "quantity": 1, "reason": "no units", "evidence_ids": [real, "none"]},
        {"id": "roof_repair", "quantity": 1, "reason": "guess", "evidence_ids": ["none"]},
    ]}))
    lines = {l["id"]: l for l in out["data"]["fitout"]["line_items"]}
    assert lines["hvac_rtu"]["evidence_ids"] == [real] and lines["roof_repair"]["evidence_ids"] == []


def test_engine_links_uncited_evidence_from_the_tool_the_agent_ran():
    from multi_agent_engine import EventLog, merge_metrics

    ctx = _ctx()
    eid = ctx.evidence.add("vexcel", "check_size_fit", "x", "fits", {"ratio_ground_floor_to_need": 1.8})
    other = ctx.evidence.add("neighborhood", "check_size_fit", "x", "not this agent's", {"r": 1})
    rep = AgentReport(agent="vexcel", label="Vexcel Agent", status="completed", metric_assessments=[
        AgentMetricAssessment(metric_id="size_fit", status="strong", rationale="fits", evidence_ids=[]),
    ])
    log = EventLog.__new__(EventLog)
    log.emit = lambda *a, **k: None  # type: ignore[method-assign]
    metrics, _ = merge_metrics(ctx, {"vexcel": rep}, log)
    m = next(m for m in metrics if m.id == "size_fit")
    assert m.evidence_ids == [eid] and other not in m.evidence_ids and m.score == 100


def test_no_vexcel_data_uses_osm_footprint_for_size_only():
    import asyncio

    from agents import vexcel_agent

    ctx = _ctx()
    ctx.property = {**ctx.property, "area_sqft": 2800, "source": "osm"}
    rep = asyncio.run(vexcel_agent.run(ctx))
    by_id = {a.metric_id: a for a in rep.metric_assessments}
    assert rep.status == "skipped" and by_id["size_fit"].status == "strong" and by_id["size_fit"].evidence_ids
    assert all(a.status == "unknown" for k, a in by_id.items() if k != "size_fit")


def test_budget_parsing_and_check():
    from services.intent import parse_budget

    b = parse_budget("40-seat restaurant in Houston with a budget of $8k/month")
    assert (b.amount, b.period) == (8000, "monthly")
    assert parse_budget("40 seat restaurant 2000 sq ft in Houston") is None  # seats/sqft are not money
    est = costs.estimate("restaurant", 1400, "houston-tx", [])
    user = costs.budget_check(est, {"amount": 1_000_000, "period": "upfront"}, "restaurant")
    assert user["source"] == "user" and user["status"] == "within" and costs.budget_status(user) == "strong"
    tight = costs.budget_check(est, {"amount": 1000, "period": "monthly"}, "restaurant")
    assert tight["status"] == "over" and costs.budget_status(tight) == "weak"
    typical = costs.budget_check(est, None, "restaurant")
    assert typical["source"] == "typical" and "didn't specify a budget" in typical["note"]


def test_quick_prefetch_registers_cited_evidence():
    from agents.base import ToolBudget, prefetch
    from agents.compliance_agent import build_tools

    ctx = _ctx()
    budget = ToolBudget(6)
    block = prefetch(build_tools(ctx, budget), [("identify_jurisdiction", {}), ("check_permitted_use", {}), ("no_such_tool", {})])
    assert block.startswith("PRE-GATHERED EVIDENCE") and "E1 [identify_jurisdiction]" in block and "E2 [check_permitted_use]" in block
    assert budget.used == 2 and len(ctx.evidence.all()) == 2


def test_quick_cost_items_come_from_evidence():
    from agents.cost_agent import pick_adders

    ctx = _ctx()
    roof = ctx.evidence.add("vexcel", "inspect_roof", "x", "0 AC units", {"roof-objects.ac-unit.count": 0, "roof-objects.roof-vent.count": 2})
    cond = ctx.evidence.add("vexcel", "inspect_roof", "x", "roof 2/5", {"roof-characteristics.condition": 2.0})
    park = ctx.evidence.add("compliance", "compute_parking_requirement", "x", "risk", {"status": "risk"})
    reqs = ctx.evidence.add("compliance", "list_use_requirements", "x", "reqs", {"items": [{"id": "grease_interceptor"}, {"id": "ada_tas"}]})
    items = {a["id"]: a for a in pick_adders(ctx)}
    assert set(items) == {"hood_exhaust", "grease_interceptor", "hvac_rtu", "roof_repair", "parking_agreement", "ada_upgrades"}
    assert items["hvac_rtu"]["evidence_ids"] == [roof] and items["roof_repair"]["evidence_ids"] == [cond]
    assert items["parking_agreement"]["evidence_ids"] == [park] and items["grease_interceptor"]["evidence_ids"] == [reqs]


def test_analysis_request_defaults_to_deep():
    from schemas import AnalysisRequest, Intent

    assert AnalysisRequest(query="q", intent=Intent(), property_id="p").mode == "deep"
    assert AnalysisRequest(query="q", intent=Intent(), property_id="p", mode="quick").mode == "quick"
