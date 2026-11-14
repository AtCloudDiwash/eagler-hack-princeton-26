"""Registry loading/filtering, scoring normalization, and config-only scaling (scale-criteria.md)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from conftest import ALL_IDS, profile

from app.config import BACKEND_DIR, settings
from app.models import CriterionResult
from app.providers.costar_provider import get_property
from app.services.agent_orchestrator import analyze_properties
from app.services.criteria_manager import CriteriaConfigError, applicable_criteria, get_criterion, load_criteria
from app.services.scoring import weighted_score

BASE = yaml.safe_load((BACKEND_DIR / "criteria.yaml").read_text())


def write_criteria(tmp_path: Path, entries, name="criteria.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(entries, sort_keys=False))
    return path


@pytest.fixture
def use_criteria(monkeypatch, tmp_path):
    counter = iter(range(1000))

    def install(entries):
        path = write_criteria(tmp_path, entries, name=f"criteria_{next(counter)}.yaml")
        monkeypatch.setattr(settings, "criteria_path", path)
        return path

    return install


def entry(id_, **kw):
    base = {"id": id_, "description": id_, "domain": "space", "weight": 10, "evaluator": "parking_checker"}
    base.update(kw)
    return base


def test_real_registry_loads_and_lookup_by_id():
    criteria = load_criteria()
    assert len(criteria) >= 11
    assert get_criterion("window_visibility").weight == 5
    assert get_criterion("nope") is None


def test_filter_by_business_type():
    restaurant = {c.id for c in applicable_criteria("restaurant")}
    dental = {c.id for c in applicable_criteria("dental_clinic")}
    assert {"kitchen_equipment", "grease_interceptor", "window_visibility"} <= restaurant
    assert "operatory_plumbing" not in restaurant
    assert "operatory_plumbing" in dental and "kitchen_equipment" not in dental


def test_filter_by_jurisdiction(use_criteria):
    use_criteria([
        entry("everywhere", applicable_jurisdictions=["ALL"]),
        entry("texas", applicable_jurisdictions=["TX"]),
        entry("austin", applicable_jurisdictions=["austin"]),
        entry("dallas", applicable_jurisdictions=["Dallas"]),
    ])
    assert {c.id for c in applicable_criteria(city="Austin", state="tx")} == {"everywhere", "texas", "austin"}
    assert {c.id for c in applicable_criteria(city="Princeton", state="NJ")} == {"everywhere"}
    assert len(applicable_criteria()) == 4  # no filter -> everything


def test_invalid_entry_names_the_entry(use_criteria):
    use_criteria([entry("good"), entry("bad_policy", missing_data_policy="hope_for_the_best")])
    with pytest.raises(CriteriaConfigError) as err:
        load_criteria()
    assert "entry #2" in str(err.value) and "bad_policy" in str(err.value) and "missing_data_policy" in str(err.value)


def test_missing_field_and_duplicates_and_shape(use_criteria):
    use_criteria([{"id": "no_evaluator", "description": "x", "domain": "space"}])
    with pytest.raises(CriteriaConfigError, match="no_evaluator.*evaluator"):
        load_criteria()
    use_criteria([entry("dup"), entry("dup")])
    with pytest.raises(CriteriaConfigError, match="duplicate"):
        load_criteria()
    use_criteria({"not": "a list"})
    with pytest.raises(CriteriaConfigError, match="YAML list"):
        load_criteria()


def _result(weight, status, counted=True):
    score = {"PASS": 1.0, "RISK": 0.0, "UNKNOWN": 0.0}[status] if counted else None
    return CriterionResult(id=f"c{weight}{status}", description="", domain="", weight=weight, status=status,
                           score=score, counted=counted, hard_block=False, notes="", source="")


def test_weighted_score_normalizes_by_counted_weight():
    assert weighted_score([_result(10, "PASS"), _result(10, "RISK")]) == 50.0
    assert weighted_score([_result(30, "PASS"), _result(10, "RISK")]) == 75.0
    # an excluded UNKNOWN does not dilute the score
    assert weighted_score([_result(30, "PASS"), _result(10, "RISK"), _result(50, "UNKNOWN", counted=False)]) == 75.0
    # adding a criterion re-normalizes: weights need not sum to 100
    assert weighted_score([_result(30, "PASS"), _result(10, "RISK"), _result(5, "RISK")]) == round(100 * 30 / 45, 1)
    assert weighted_score([]) == 0.0


def _analyze(ids=ALL_IDS):
    return {r.property_id: r for r in analyze_properties(profile(), [get_property(i) for i in ids]).results}


def test_adding_a_criterion_via_config_changes_results(use_criteria):
    """scale-criteria.md: config-only scaling. A property below the window threshold loses score."""
    without = [e for e in BASE if e["id"] != "window_visibility"]
    use_criteria(without)
    before = _analyze()
    assert all("window_visibility" not in r.compliance for r in before.values())

    window = next(e for e in BASE if e["id"] == "window_visibility")
    strict = {**window, "thresholds": {"min_area": 50}}  # 456 has 35 sq ft of glass -> RISK
    use_criteria(without + [strict])
    after = _analyze()
    r456 = after["property-456"]
    assert r456.compliance["window_visibility"].status == "RISK"
    assert before["property-456"].score == 100.0
    total = sum(e["weight"] for e in without if e["weight"] > 0 and e["id"] != "operatory_plumbing")
    assert r456.score == round(100 * total / (total + 5), 1)  # max score re-normalized by the new weight
    assert after["property-123"].compliance["window_visibility"].status == "PASS"  # 60 sq ft
    # no window data on 789 -> ignore policy -> shown, not scored
    wv = next(c for c in after["property-789"].criteria_results if c.id == "window_visibility")
    assert wv.status == "UNKNOWN" and wv.counted is False


def test_weight_change_takes_effect_without_code_change(use_criteria):
    bumped = [{**e, "weight": 100} if e["id"] == "parking_sufficiency" else e for e in BASE]
    use_criteria(BASE)
    base_score = _analyze(["property-123"])["property-123"].score
    use_criteria(bumped)
    assert _analyze(["property-123"])["property-123"].score < base_score  # 123 fails parking


def test_min_score_gate_is_config_driven(monkeypatch):
    """costs.yaml ranking.min_score: weak fits rank after qualifying spaces; 0 restores cost-only order."""
    from app.services import agent_orchestrator

    real = agent_orchestrator.cost_config()

    def with_min_score(value):
        cfg = {**real, "ranking": {**real.get("ranking", {}), "min_score": value}}
        monkeypatch.setattr(agent_orchestrator, "cost_config", lambda: cfg)
        return analyze_properties(profile(), [get_property(i) for i in ALL_IDS])

    gated = with_min_score(25)
    assert gated.min_score == 25
    assert [r.property_id for r in gated.results] == ["property-456", "property-123", "property-321", "property-789"]
    assert {r.property_id for r in gated.results if r.weak_fit} == {"property-321"}

    cost_only = with_min_score(0)
    assert cost_only.min_score == 0 and not any(r.weak_fit for r in cost_only.results)
    assert [r.property_id for r in cost_only.results] == ["property-456", "property-321", "property-123", "property-789"]
    assert "at least" not in cost_only.ranking_basis

    # A high bar makes every eligible space a weak fit; disqualified still ranks last and is never "weak".
    strict = with_min_score(101)
    assert [r.weak_fit for r in strict.results] == [True, True, True, False]
    assert strict.results[-1].disqualified
