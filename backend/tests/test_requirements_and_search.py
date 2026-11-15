"""The user's stated requirements drive the verdict, and search parsing/filtering is robust (offline)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import pytest  # noqa: E402

from schemas import Intent  # noqa: E402
from services import scoring, vexcel, visual  # noqa: E402
from services.external import expand_aliases  # noqa: E402
from services.intent import parse_rules, split_needs  # noqa: E402

GOOD = [{"id": f"m{i}", "weight": 10, "status": "strong", "score": 100.0, "evidence_ids": ["E1"], "hard_block": False} for i in range(8)]


def _rec(checks, budgets=()):
    rec = scoring.overall(GOOD + scoring.requirement_rows(checks))
    return scoring.cap_for_requirements(rec, checks, list(budgets))


def test_met_requirements_keep_recommended():
    rec = _rec([{"requirement": "parking", "status": "met", "evidence_ids": ["E2"]}])
    assert rec["verdict"] == "recommended" and rec["caps"] == []


def test_unmet_requirement_lowers_score_and_caps_verdict():
    base = scoring.overall(GOOD)["score"]
    rec = _rec([{"requirement": "drive-thru", "status": "unmet", "evidence_ids": ["E2"]}])
    assert rec["score"] < base and rec["verdict"] == "conditional" and "drive-thru" in rec["caps"][0]
    two = _rec([{"requirement": "drive-thru", "status": "unmet", "evidence_ids": ["E2"]}, {"requirement": "patio", "status": "unmet", "evidence_ids": ["E3"]}])
    assert two["verdict"] == "not_recommended"


def test_unknown_requirements_are_not_scored():
    rec = _rec([{"requirement": "grease trap", "status": "unknown", "evidence_ids": []}])
    assert rec["score"] == scoring.overall(GOOD)["score"] and rec["verdict"] == "recommended"


def test_requirement_weight_is_capped():
    rows = scoring.requirement_rows([{"requirement": f"r{i}", "status": "met", "evidence_ids": []} for i in range(10)])
    assert sum(r["weight"] for r in rows) == pytest.approx(scoring.REQUIREMENT_WEIGHT_CAP)


def test_budget_caps():
    over = {"source": "user", "period": "monthly", "amount": 6000, "compare_low": 15000, "compare_high": 18000, "status": "over"}
    assert _rec([], [over])["verdict"] == "not_recommended"  # low estimate 150% over
    slightly = {**over, "compare_low": 6500, "compare_high": 8000}
    assert _rec([], [slightly])["verdict"] == "conditional"
    typical = {**over, "source": "typical"}  # no stated budget: never caps
    assert _rec([], [typical])["verdict"] == "recommended"


def test_budget_requirement_not_capped_twice():
    over = {"source": "user", "period": "upfront", "amount": 80000, "compare_low": 274867, "compare_high": 690600, "status": "over"}
    rec = _rec([{"requirement": "budget under $80k", "status": "unmet", "evidence_ids": ["E1"]}], [over])
    assert rec["verdict"] == "not_recommended" and len(rec["caps"]) == 1 and "budget of $80,000" in rec["caps"][0]


@pytest.mark.parametrize("query,btype,loc", [
    ("bakery in Los Angeles, CA, budget $5k/month", "restaurant", "Los Angeles, CA"),
    ("barber shop in Houston", "retail", "Houston"),
    ("coffee shop in Houston TX 1500 sqft", "restaurant", "Houston TX"),
    ("interested in opening a bakery in Pasadena", "restaurant", "Pasadena"),
    ("restaurant in houston near offices", "restaurant", "houston"),
    ("dental clinic at 1919 Louisiana St, Houston with parking", "dental_clinic", "1919 Louisiana St, Houston"),
    ("restaurants in Midtown Houston", "restaurant", "Midtown Houston"),
])
def test_rule_parser(query, btype, loc):
    i = parse_rules(query)
    assert (i.business_type, i.location_text) == (btype, loc)


def test_split_needs():
    assert split_needs("need a grease trap, near offices and walkable. Budget $6k/month; must have outdoor patio") == ["grease trap", "near offices", "walkable", "outdoor patio"]


def test_aliases():
    assert expand_aliases("Downtown LA") == "Downtown Los Angeles" and expand_aliases("DTLA") == "Downtown Los Angeles"
    assert expand_aliases("Plano") == "Plano"


def test_too_low_keeps_large_buildings():
    assert vexcel._too_low({"roof-characteristics.height": 5, "footprint.area": 300})  # kiosk
    assert not vexcel._too_low({"roof-characteristics.height": -0.7, "footprint.area": 62000})  # bad elevation data
    assert not vexcel._too_low({"roof-characteristics.height": 14, "footprint.area": 300})


def test_visual_needs_read_from_query_text():
    intent = Intent(business_type="restaurant", business_label="Restaurant", requirements=[])
    keys = list(visual.config()["phrases"])
    assert visual.visual_phrases(intent, f"restaurant with a {keys[0]} in Houston")
