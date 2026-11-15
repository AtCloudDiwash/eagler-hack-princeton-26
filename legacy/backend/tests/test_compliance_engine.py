"""Registry semantics: missing-data policies, evidence_required, hard_block, unknown evaluators."""
from __future__ import annotations

from conftest import make_criterion, make_ctx, make_property, obs

from app.config import business_types, jurisdiction_for
from app.services.compliance_engine import check_ada, check_parking, evaluate_criterion, run_compliance
from app.services.evaluators import EvalOutcome, evaluator


def evaluate(criterion, requirements, observations=None, prop=None):
    return evaluate_criterion(criterion, make_ctx(criterion, requirements, prop=prop, observations=observations))


def test_missing_input_is_unknown_and_assume_risk_scores_zero(restaurant_req):
    c = make_criterion(evaluator="bathroom_checker", required_inputs=["bathrooms_visible", "business_required_bathrooms"],
                       missing_data_policy="assume_risk")
    result, outcome = evaluate(c, restaurant_req)
    assert result.status == "UNKNOWN"
    assert result.counted is True and result.score == 0.0
    assert "could not confirm the number of restrooms" in result.notes
    assert outcome.questions and not outcome.cost_items


def test_assume_cost_adds_fallback_cost(restaurant_req):
    c = make_criterion(evaluator="grease_checker", required_inputs=["grease_interceptor_present"], missing_data_policy="assume_cost")
    result, outcome = evaluate(c, restaurant_req)
    assert result.status == "UNKNOWN" and result.counted and result.score == 0.0
    assert [n.item for n in outcome.cost_items] == ["grease_interceptor"]


def test_unknown_and_ignore_policies_are_excluded(restaurant_req):
    for policy in ("unknown", "ignore"):
        c = make_criterion(evaluator="check_window_visibility", required_inputs=["window_area"], missing_data_policy=policy)
        result, outcome = evaluate(c, restaurant_req)
        assert result.status == "UNKNOWN" and result.counted is False and result.score is None
        assert not outcome.cost_items


def test_evidence_required_downgrades_unobserved_pass(restaurant_req):
    c = make_criterion(evaluator="kitchen_checker", required_inputs=[], evidence_required=True)
    not_needed = restaurant_req.model_copy(update={"needs_kitchen": False})
    result, _ = evaluate(c, not_needed)  # PASS with no observed evidence
    assert result.status == "UNKNOWN" and "No observed evidence" in result.notes
    result, _ = evaluate(c, not_needed, obs(kitchen_equipment_visible=False))
    assert result.status == "PASS"


def test_requirements_only_evidence_does_not_count_as_observed(restaurant_req):
    @evaluator("_test_requirements_only")
    def _fn(ctx):
        return EvalOutcome("PASS", "ok", [ctx.derived("x", 1, "derived")])

    c = make_criterion(evaluator="_test_requirements_only", evidence_required=True)
    result, _ = evaluate(c, restaurant_req)
    assert result.status == "UNKNOWN"


def test_hard_block_only_on_definitive_failure(restaurant_req):
    zoning = make_criterion(id="zoning_use", evaluator="zoning_checker", required_inputs=["zoning_code"],
                            hard_block=True, missing_data_policy="unknown", evidence_required=True)
    prohibited, _ = evaluate(zoning, restaurant_req, obs("costar", zoning_code="LO"))
    assert prohibited.status == "RISK" and prohibited.blocking is True
    conditional, _ = evaluate(zoning, restaurant_req, obs("costar", zoning_code="LR"))
    assert conditional.status == "RISK" and conditional.blocking is False
    missing, _ = evaluate(zoning, restaurant_req)
    assert missing.status == "UNKNOWN" and missing.blocking is False  # missing data never blocks


def test_non_definitive_risk_on_hard_block_criterion_does_not_block(restaurant_req):
    c = make_criterion(evaluator="parking_checker", hard_block=True,
                       required_inputs=["visible_parking_count", "business_required_parking"])
    result, _ = evaluate(c, restaurant_req, obs("vexcel", visible_parking_count=1))
    assert result.status == "RISK" and result.blocking is False


def test_unknown_evaluator_name_does_not_crash(restaurant_req):
    c = make_criterion(evaluator="does_not_exist", missing_data_policy="assume_risk")
    result, _ = evaluate(c, restaurant_req)
    assert result.status == "UNKNOWN" and "does_not_exist" in result.notes and result.blocking is False


def test_crashing_evaluator_becomes_unknown(restaurant_req):
    @evaluator("_test_crash")
    def _crash(ctx):
        raise RuntimeError("kaboom")

    result, _ = evaluate(make_criterion(evaluator="_test_crash"), restaurant_req)
    assert result.status == "UNKNOWN" and "kaboom" in result.notes


def test_weight_zero_is_shown_but_not_scored(restaurant_req):
    c = make_criterion(evaluator="fire_safety_checker", weight=0, required_inputs=["occupant_load", "size_sqft"])
    result, _ = evaluate(c, restaurant_req)
    assert result.status == "PASS" and result.counted is False and result.score is None


def test_run_compliance_collects_costs_questions_and_disqualifiers(restaurant_req):
    criteria = [
        make_criterion(id="zoning_use", evaluator="zoning_checker", required_inputs=["zoning_code"], hard_block=True),
        make_criterion(id="grease", evaluator="grease_checker", required_inputs=["grease_interceptor_present"],
                       missing_data_policy="assume_cost"),
    ]
    prop = make_property(zoning="LO")
    report = run_compliance(criteria, restaurant_req, prop, obs("costar", zoning_code="LO"),
                            jurisdiction_for("Austin", "TX"), business_types()["restaurant"])
    assert report.disqualifiers == ["zoning_use"]
    assert [n.item for n in report.cost_needs] == ["grease_interceptor"]
    assert report.score == 0.0
    assert set(report.compliance) == {"zoning_use", "grease"}
    assert any("assume_cost" in a for a in report.assumptions)


def test_simple_helpers():
    assert check_parking(15, 20)[0] == "RISK"
    assert check_parking(22, 20)[0] == "PASS"
    assert check_parking(None, 20)[0] == "UNKNOWN"
    assert check_ada(36)[0] == "PASS"
    assert check_ada(30)[0] == "RISK"
    assert check_ada(None)[0] == "UNKNOWN"
