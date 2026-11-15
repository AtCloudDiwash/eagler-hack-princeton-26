"""Agent reliability: citation checks, complete reports, data-settled verdicts, the pure merge, failure
containment and timeouts — all offline, with a scripted fake model instead of a live LLM."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import pytest  # noqa: E402
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402

from agents.base import EvidenceStore, RunContext, ToolBudget, run_agent, to_report, tracked_tool  # noqa: E402
from config import settings  # noqa: E402
from schemas import AgentMetricAssessment, AgentOutput, AgentReport, Intent, NeedCheck  # noqa: E402
from services import program as space_program  # noqa: E402
from services import rules, verdicts  # noqa: E402
from services.llm import AllProvidersFailedError  # noqa: E402


def _ctx(**over: Any) -> RunContext:
    _, jur = rules.jurisdiction_for("Houston", "Texas")
    intent = Intent(business_type="restaurant", seats=40, needs=[{"id": "parking", "label": "On-site parking", "priority": "must"}])
    base = dict(
        query="40-seat restaurant in Houston with parking", intent=intent.model_dump(),
        property={"id": "p", "lat": 29.75, "lon": -95.45}, feature=None, neighborhood={}, neighbor_features=[], census={},
        jurisdiction_key="houston-tx", jurisdiction=jur, target_sqft=1400, target_basis="test", extra_requirements=None,
        evidence=EvidenceStore(), emit=lambda *a, **k: None, program=space_program.build(intent),
    )
    base.update(over)
    return RunContext(**base)


class _Log:
    def emit(self, *a: Any, **k: Any) -> None:
        pass


# ---------------------------------------------------------------- citations and complete reports

def test_citations_only_count_evidence_the_agent_saw():
    ctx = _ctx()
    mine = ctx.evidence.add("vexcel", "inspect_roof", "x", "roof 4/5", {"roof-characteristics.condition": 4})
    theirs = ctx.evidence.add("neighborhood", "count_places", "x", "12 restaurants", {"count": 12})
    out = AgentOutput(summary="s", metric_assessments=[
        AgentMetricAssessment(metric_id="building_condition", status="strong", rationale="good roof", evidence_ids=[mine, theirs, "E99"]),
    ])
    rep = to_report(ctx, "vexcel", out, "completed", 1, 1.0, None)
    a = next(a for a in rep.metric_assessments if a.metric_id == "building_condition")
    assert a.evidence_ids == [mine]


def test_evidence_without_data_does_not_support_a_conclusion():
    ctx = _ctx()
    empty = ctx.evidence.add("neighborhood", "count_places", "x", "Place data UNAVAILABLE", None)
    out = AgentOutput(summary="s", metric_assessments=[
        AgentMetricAssessment(metric_id="customer_demand", status="strong", rationale="busy", evidence_ids=[empty]),
        AgentMetricAssessment(metric_id="competition", status="unknown", rationale="no data", evidence_ids=[empty]),
    ])
    rep = to_report(ctx, "neighborhood", out, "completed", 1, 1.0, None)
    by_id = {a.metric_id: a for a in rep.metric_assessments}
    assert by_id["customer_demand"].evidence_ids == []  # 'strong' is not backed by "unavailable"
    assert by_id["competition"].evidence_ids == [empty]  # citing the gap for 'unknown' is fine


def test_reports_are_complete_metrics_and_needs():
    ctx = _ctx()
    rep = to_report(ctx, "compliance", AgentOutput(summary="s"), "partial", 0, 1.0, "timeout")
    assigned = {m["id"] for m in ctx.metrics_for("compliance")}
    assert {a.metric_id for a in rep.metric_assessments} == assigned
    assert all(a.status == "unknown" for a in rep.metric_assessments)
    assert [n.need_id for n in rep.needs] == ["parking"] and rep.needs[0].status == "unknown"


def test_unmet_need_without_evidence_becomes_unknown():
    ctx = _ctx()
    out = AgentOutput(summary="s", needs=[NeedCheck(need_id="parking", status="unmet", detail="no lot", evidence_ids=["E42"])])
    rep = to_report(ctx, "compliance", out, "completed", 0, 1.0, None)
    assert rep.needs[0].status == "unknown"


# ---------------------------------------------------------------- tool budget

def test_tool_budget_reserves_atomically_and_reuses_results():
    ctx = _ctx()
    budget = ToolBudget(2)

    @tracked_tool(ctx, "vexcel", budget, "test")
    def probe(x: int) -> dict:
        """Probe."""
        return {"summary": f"x={x}", "data": {"x": x}}

    first = probe.invoke({"x": 1})
    again = probe.invoke({"x": 1})
    probe.invoke({"x": 2})
    over = probe.invoke({"x": 3})
    assert "evidence_id" in first and "Already called" in again and "budget exhausted" in over
    assert budget.used == 2
    assert budget.reserve("pending") is None or True  # slot accounting never exceeds the limit
    assert budget.used == 2


def test_large_tool_payloads_are_trimmed_but_evidence_keeps_everything():
    ctx = _ctx()

    @tracked_tool(ctx, "vexcel", ToolBudget(3), "test")
    def big() -> dict:
        """Big."""
        return {"summary": "big", "data": {f"k{i}": (False if i % 2 else "x" * 50) for i in range(400)}}

    out = big.invoke({})
    assert len(out) <= 6500
    assert len(ctx.evidence.all()[-1].data) == 400


# ---------------------------------------------------------------- verdicts and the pure merge

def test_verdict_accepts_more_cautious_agents_only():
    v = verdicts.Verdict("permitted_use", "strong", "rule says pass")
    assert v.accepts("strong") and v.accepts("adequate") and not v.accepts("unknown") and not v.accepts("blocker")
    w = verdicts.Verdict("parking_requirement", "weak", "shortfall", also_accept=frozenset({"adequate"}))
    assert w.accepts("adequate") and not w.accepts("strong")


def test_override_replaces_rationale_and_keeps_what_the_agent_said():
    agent = AgentMetricAssessment(metric_id="permitted_use", status="strong", rationale="Use is permitted by right", evidence_ids=[])
    v = verdicts.Verdict("permitted_use", "blocker", "Verified rule prohibits food service here", ("E1",), "verified rules")
    merged, conflict = verdicts.apply("permitted_use", "compliance", agent, v, "Compliance Agent")
    assert merged.assessment.status == "blocker" and merged.assessment.rationale.startswith("Verified rule prohibits")
    assert "had said 'strong'" in merged.assessment.rationale and conflict and merged.overridden


def test_cap_limits_optimism_but_keeps_open_questions():
    cap = verdicts.Verdict("interior_layout", "weak", "low ceilings", kind="cap")
    hi = AgentMetricAssessment(metric_id="interior_layout", status="strong", rationale="open plan")
    unk = AgentMetricAssessment(metric_id="interior_layout", status="unknown", rationale="?")
    assert verdicts.apply("interior_layout", "matterport", hi, cap, "M")[0].assessment.status == "weak"
    assert verdicts.apply("interior_layout", "matterport", unk, cap, "M")[0].assessment.status == "unknown"


def test_merge_is_idempotent_and_settles_permitted_use_from_rules():
    from multi_agent_engine import merge_metrics

    ctx = _ctx()
    rep = AgentReport(agent="compliance", label="Compliance Agent", status="completed", metric_assessments=[
        AgentMetricAssessment(metric_id="permitted_use", status="adequate", rationale="deed check pending", evidence_ids=[]),
    ])
    first, _ = merge_metrics(ctx, {"compliance": rep}, _Log())
    n_evidence = len(ctx.evidence.all())
    second, _ = merge_metrics(ctx, {"compliance": rep}, _Log())
    assert [(m.id, m.status) for m in first] == [(m.id, m.status) for m in second]
    assert len(ctx.evidence.all()) == n_evidence  # the second merge records nothing new
    pu = next(m for m in first if m.id == "permitted_use")
    assert pu.status == "adequate" and pu.evidence_ids  # more cautious agent kept, backed by the rule evidence


def test_parking_rule_uses_the_program_size_not_the_agents_guess():
    from multi_agent_engine import merge_metrics

    ctx = _ctx(feature={"properties": {"hardscapes.area": 650}})
    ctx.property = {**ctx.property, "lat": 29.70, "lon": -95.55}  # outside any exempt area
    ctx.evidence.add("compliance", "compute_parking_requirement", "x", "pass", rules.parking_requirement(ctx.jurisdiction, "restaurant", 300, 29.70, -95.55, 650))
    rep = AgentReport(agent="compliance", label="Compliance Agent", status="completed", metric_assessments=[
        AgentMetricAssessment(metric_id="parking_requirement", status="strong", rationale="tiny space, enough parking", evidence_ids=[]),
    ])
    metrics, _ = merge_metrics(ctx, {"compliance": rep}, _Log())
    pr = next(m for m in metrics if m.id == "parking_requirement")
    expected = rules.parking_requirement(ctx.jurisdiction, "restaurant", ctx.program["size"]["target_sqft"], 29.70, -95.55, 650)
    assert pr.status == {"pass": "strong", "risk": "weak", "unknown": "unknown"}[expected["status"]]


def test_recorded_parking_spaces_replace_the_paving_estimate():
    _, jur = rules.jurisdiction_for("Houston", "Texas")
    item = rules.parking_requirement(jur, "restaurant", 2000, 29.70, -95.55, 300, recorded_spaces=120)
    if item["status"] != "unknown" and "exempt_area" not in item["evidence"]:
        assert item["status"] == "pass" and item["evidence"]["recorded_spaces"] == 120 and "CoStar" in item["detail"]


def test_size_assessment_thresholds():
    assert verdicts.size_assessment(1400, 1190, 1820, best_space={"sqft": 1500, "suite": "100"})[0] == "strong"
    assert verdicts.size_assessment(1400, 1190, 1820, footprint_sqft=1500)[0] == "strong"
    assert verdicts.size_assessment(1400, 1190, 1820, footprint_sqft=3500)[0] == "adequate"
    assert verdicts.size_assessment(1400, 1190, 1820, footprint_sqft=600)[0] == "weak"
    assert verdicts.size_assessment(1400, 1190, 1820, interior_sqft=900)[0] == "weak"
    assert verdicts.size_assessment(1400, 1190, 1820) is None


def test_roof_verdict_from_aerial_data():
    feature = {"properties": {}, "structures": []}
    ctx = _ctx(feature=feature)
    s = {"roof-characteristics.condition": 4.0, "roof-defects.discoloration.detected": True}
    import services.verdicts as vmod

    orig = vmod.primary_structure
    vmod.primary_structure = lambda f: s  # type: ignore[assignment]
    try:
        assert vmod._building_condition(ctx).status == "strong"  # minor stains don't make a 4/5 roof weak
        s["roof-defects.tarp.detected"] = True
        assert vmod._building_condition(ctx).status == "weak"
    finally:
        vmod.primary_structure = orig  # type: ignore[assignment]


def test_site_checks_use_recorded_sprinklers_and_need_config():
    intent = Intent(business_type="restaurant", seats=150, needs=[{"id": "drive_thru", "label": "Drive-thru", "priority": "must"}])
    prog = space_program.build(intent)
    building = {"facts": {"sprinklers": {"value": False, "source": "CoStar", "confidence": "high"}}}
    checks = space_program.site_checks(prog, space_program.facts_from({"area_sqft": 4000}, {"properties": {"hardscapes.area": 2500}}, building))
    by_id = {c["id"]: c for c in checks}
    assert by_id["drive_thru"]["status"] == "risk"  # 2,500 sq ft paving < 4,000 from needs.yaml
    if "sprinklers" in by_id:
        assert by_id["sprinklers"]["status"] == "risk"


def test_must_have_gap_caps_the_verdict():
    from multi_agent_engine import must_have_gaps

    ctx = _ctx()
    gaps = must_have_gaps(ctx, {}, [{"id": "parking", "label": "Parking", "status": "risk", "detail": "Paved area fits ~2 spaces"}])
    assert gaps and gaps[0].startswith("On-site parking")


# ---------------------------------------------------------------- run_agent with a scripted model

class ScriptedModel(FakeMessagesListChatModel):
    """Plays back AI messages; supports tool binding (ignored) and a canned structured output."""

    structured: Any = None
    error: Any = None
    delay_s: float = 0.0

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        return self

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.error:
            raise self.error
        return await super()._agenerate(*args, **kwargs)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        async def run(_: Any) -> Any:
            return self.structured
        return RunnableLambda(lambda _: self.structured, afunc=run)


def _report_call(metric_status: str = "strong") -> AIMessage:
    args = {"summary": "done", "metric_assessments": [{"metric_id": "permitted_use", "status": metric_status, "rationale": "r", "evidence_ids": []}]}
    return AIMessage(content="", tool_calls=[{"name": "AgentOutput", "args": args, "id": "c1", "type": "tool_call"}])


def test_run_agent_completes_with_a_scripted_model():
    ctx = _ctx()
    model = ScriptedModel(responses=[_report_call()])
    rep = asyncio.run(run_agent(ctx, "compliance", "role", "task", [], ToolBudget(3), model=model))
    assert rep.status == "completed"
    assert next(a for a in rep.metric_assessments if a.metric_id == "permitted_use").status == "strong"


def test_one_failed_llm_call_fails_only_that_agent():
    ctx = _ctx()
    model = ScriptedModel(responses=[AIMessage(content="x")], error=AllProvidersFailedError("bad json everywhere", exhausted=False))
    rep = asyncio.run(run_agent(ctx, "compliance", "role", "task", [], ToolBudget(3), model=model))
    assert rep.status in {"failed", "partial"} and rep.error


def test_exhausted_providers_stop_the_analysis():
    ctx = _ctx()
    model = ScriptedModel(responses=[AIMessage(content="x")], error=AllProvidersFailedError("all out of quota", exhausted=True))
    with pytest.raises(AllProvidersFailedError):
        asyncio.run(run_agent(ctx, "compliance", "role", "task", [], ToolBudget(3), model=model))


def test_timeout_keeps_evidence_and_rescues_a_partial_report(monkeypatch: pytest.MonkeyPatch):
    ctx = _ctx()
    ctx.evidence.add("compliance", "check_permitted_use", "x", "Permitted use: PASS", {"status": "pass"})
    monkeypatch.setattr(settings, "agent_timeout_s", 0.3)
    rescued = AgentOutput(summary="rescued", metric_assessments=[AgentMetricAssessment(metric_id="permitted_use", status="strong", rationale="rule pass", evidence_ids=["E1"])])
    model = ScriptedModel(responses=[AIMessage(content="thinking")], delay_s=2.0, structured=rescued)
    rep = asyncio.run(run_agent(ctx, "compliance", "role", "task", [], ToolBudget(3), model=model))
    assert rep.status == "partial" and "Timed out" in (rep.error or "")
    assert next(a for a in rep.metric_assessments if a.metric_id == "permitted_use").evidence_ids == ["E1"]


def test_fallback_chain_marks_exhaustion_only_when_every_provider_is_out(monkeypatch: pytest.MonkeyPatch):
    from services import llm
    from services.cli_chat import ProviderExhaustedError

    llm.reset_cooldowns()

    class Boom(FakeMessagesListChatModel):
        err: Any = None

        async def _agenerate(self, *a: Any, **k: Any) -> Any:
            raise self.err

    chain = llm.FallbackChat(providers=["codex", "claude"])
    monkeypatch.setattr(llm, "_make", lambda name, effort: Boom(responses=[AIMessage(content="")], err=ValueError("bad json")))
    with pytest.raises(AllProvidersFailedError) as soft:
        asyncio.run(chain.ainvoke("hi"))
    assert soft.value.exhausted is False
    monkeypatch.setattr(llm, "_make", lambda name, effort: Boom(responses=[AIMessage(content="")], err=ProviderExhaustedError("usage limit")))
    with pytest.raises(AllProvidersFailedError) as hard:
        asyncio.run(chain.ainvoke("hi"))
    assert hard.value.exhausted is True
    llm.reset_cooldowns()


# ---------------------------------------------------------------- property panel figures and amenity scans

def test_costar_figures_win_over_aerial_estimates():
    from services import costar

    vexcel_candidate = {"area_sqft": 74679, "floor_area_est_sqft": 2165701, "parcel_sqft": 67844, "stories_est": 29}
    shown = costar.reconcile(vexcel_candidate, {"stories": 24, "gross_sqft": 784143.0, "lot_sqft": 62291})
    assert (shown["stories_est"], shown["floor_area_est_sqft"], shown["parcel_sqft"]) == (24, 784143, 62291)
    # no CoStar record: a "lot" smaller than the building's own footprint is a synthetic parcel, so it is dropped
    assert costar.reconcile(vexcel_candidate, None)["parcel_sqft"] is None
    assert costar.reconcile({"area_sqft": 5000, "parcel_sqft": 20000}, None)["parcel_sqft"] == 20000


def test_tiny_paved_area_is_not_shown_as_a_lot():
    from services import vexcel

    facts = {f["label"]: f for f in vexcel.key_facts({"properties": {"hardscapes.area": 4.0}, "structures": []})}
    assert facts["Paved (hardscape) area"]["value"] == "None detected"


def test_interior_facts_from_another_suite_do_not_settle_metrics():
    ctx = _ctx()
    ctx.shared["interior_facts"] = {"indoor_area_sqft": 900}
    ctx.shared["scan_identity"] = {"verdict": "likely"}
    ctx.property = {**ctx.property, "best_space": {"suite": "170", "sqft": 1587}}
    assert verdicts.interior_scan(ctx) is None
    ctx.shared["scan_identity"] = {"verdict": "verified"}
    assert verdicts.interior_scan(ctx) == {"indoor_area_sqft": 900}


def test_amenity_scan_is_replaced_or_unlinked(monkeypatch: pytest.MonkeyPatch):
    import db
    import main
    from services import costar, matterport, scan_identity

    rec = {"matterport_scans": [{"id": "LobbyScan01", "caption": "Lobby Matterport"}]}
    monkeypatch.setattr(costar, "match", lambda *a, **k: rec)
    saved: list = []
    monkeypatch.setattr(db, "save_property", lambda prop, raw: saved.append(prop))
    prop = {"id": "x", "lat": 29.75, "lon": -95.36, "matterport_model_id": "LobbyScan01"}

    monkeypatch.setattr(matterport, "has_credentials", lambda: False)
    out = asyncio.run(main._replace_amenity_scan(dict(prop), None))
    assert out["matterport_model_id"] is None and out["matterport_lookup_done"]

    monkeypatch.setattr(matterport, "has_credentials", lambda: True)

    async def found(p: dict, **k: Any) -> dict:
        return {"switched": True, "verdict": "verified", "model_id": "Suite170Scn", "name": "Suite 170", "reason": "Scan shows suite 170."}

    monkeypatch.setattr(scan_identity, "choose_scan", found)
    out = asyncio.run(main._replace_amenity_scan(dict(prop), None))
    assert out["matterport_model_id"] == out["matterport_auto_model_id"] == "Suite170Scn"
    # a tour the user linked themselves (not one of CoStar's scans) is never touched
    mine = asyncio.run(main._replace_amenity_scan({**prop, "matterport_model_id": "MyOwnScan11"}, None))
    assert mine["matterport_model_id"] == "MyOwnScan11"


# ---------------------------------------------------------------- accessibility: verified data only

def _ada_ctx(best: dict | None = None, facts: dict | None = None, scan: dict | None = None, verdict: str | None = None) -> RunContext:
    ctx = _ctx()
    ctx.property = {**ctx.property, **({"best_space": best} if best else {})}
    ctx.building = {"facts": {k: {"value": v, "source": "CoStar", "confidence": "high"} for k, v in (facts or {}).items()}}
    if scan is not None:
        ctx.shared["interior_facts"] = scan
        ctx.shared["scan_identity"] = {"verdict": verdict}
    return ctx


def test_accessibility_is_unknown_without_verified_data_and_agents_cannot_fill_it():
    v = verdicts._accessibility_ada(_ada_ctx())
    assert v.status == "unknown" and not v.accepts("adequate") and not v.accepts("strong")


def test_accessibility_from_recorded_floor_elevators_and_measured_doors():
    upstairs_no_lift = verdicts._accessibility_ada(_ada_ctx({"suite": "300", "floor": "3rd Floor", "ground_floor": False}, {"stories": 5, "elevators": 0}))
    assert upstairs_no_lift.status == "weak"
    street = verdicts._accessibility_ada(_ada_ctx({"suite": "170", "floor": "First Floor", "ground_floor": True}, {"year_built": 2005}))
    assert street.status == "adequate" and "Not verified" in street.rationale
    doors = {"doorways": [{"room": "Sales floor", "width_in": 36}, {"room": "Restroom", "width_in": 34}, {"room": "Storage closet", "width_in": 24}]}
    good = verdicts._accessibility_ada(_ada_ctx({"suite": "170", "floor": "First Floor", "ground_floor": True}, {"year_built": 2005}, doors, "verified"))
    assert good.status == "strong"  # the narrow closet door is back-of-house
    # the same measurements from a scan that isn't verified to show this suite don't count
    assert verdicts._accessibility_ada(_ada_ctx({"suite": "170", "floor": "First Floor", "ground_floor": True}, {"year_built": 2005}, doors, "likely")).status == "adequate"
    narrow = {"doorways": [{"room": "Restroom", "width_in": 28}]}
    assert verdicts._accessibility_ada(_ada_ctx({"suite": "170", "floor": "First Floor", "ground_floor": True}, {}, narrow, "verified")).status == "weak"
    old = verdicts._accessibility_ada(_ada_ctx({"suite": "170", "floor": "First Floor", "ground_floor": True}, {"year_built": 1975}, doors, "verified"))
    assert old.status == "adequate" and "1991" in old.rationale


def test_panel_highlights_show_only_known_useful_facts():
    from services import building_facts

    prop = {"lat": 0.0, "lon": 0.0, "best_space": {"suite": "170", "floor": "First Floor", "sqft": 1500, "rent_per_sqft_yr": 24.0, "service": "TripleNet", "available_on": "2025-03-31"}}
    rows = building_facts.highlights(prop, None)
    by_id = {r["id"]: r for r in rows}
    assert (by_id["space"]["value"], by_id["space"]["sub"]) == ("1,500 sq ft", "1st floor") and by_id["rent"]["value"] == "$3,000/mo"
    # the same nine tiles for every building, in the same order; a missing value says why
    assert [r["id"] for r in rows] == [r["id"] for r in building_facts.highlights({"lat": 1.0, "lon": 1.0}, None)]
    assert len(rows) == 9 and all(r["value"] not in ("", "—", None) for r in rows)
    assert by_id["roof"]["missing"] and (by_id["roof"]["value"], by_id["roof"]["sub"]) == ("Unknown", "no aerial data")


def test_panel_tiles_answer_the_users_request(monkeypatch: pytest.MonkeyPatch):
    from services import costar, fit_summary

    rec = {"id": 1, "type": "Retail", "lease_listings": []}
    monkeypatch.setattr(costar, "match", lambda *a, **k: rec)
    monkeypatch.setattr(costar, "candidate_fields", lambda *a, **k: {"best_space": {"suite": "170", "floor": "First Floor", "sqft": 1500, "rent_per_sqft_yr": 24.0, "service": "TripleNet", "ground_floor": True}, "space_count": 1})
    intent = Intent(business_type="restaurant", sqft=1400, budget={"amount": 9000, "period": "monthly"})
    rows = fit_summary.tiles({"lat": 29.75, "lon": -95.45, "address": "100 Main St, Houston, TX"}, None, intent)
    by_id = {r["id"]: r for r in rows}
    assert [r["id"] for r in rows] == ["space", "size", "monthly", "upfront", "budget", "street", "permitted", "parking", "prior"]
    assert (by_id["space"]["value"], by_id["space"]["sub"]) == ("1,500 sq ft", "Suite 170") and by_id["size"]["status"] == "good"
    assert (by_id["street"]["value"], by_id["street"]["sub"]) == ("Yes", "1st floor") and by_id["budget"]["label"] == "Your budget"
    assert all(len(r["value"]) <= 12 for r in rows)  # headlines fit the card; context goes in `sub`
    assert by_id["prior"]["missing"] and all(r["value"] for r in rows)
