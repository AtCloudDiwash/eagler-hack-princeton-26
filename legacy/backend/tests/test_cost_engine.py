from __future__ import annotations

import pytest
from conftest import make_property

from app.config import business_types
from app.services.cost_engine import UnknownCostItem, estimate, estimate_cost, estimate_kitchen_cost, merge_needs, price_item
from app.services.evaluators import CostNeed

RESTAURANT = business_types()["restaurant"]


def test_price_each_and_per_sqft():
    assert price_item("kitchen_install", 1).model_dump(include={"min", "max"}) == {"min": 40000, "max": 60000}
    assert price_item("restroom_add", 2).model_dump(include={"min", "max"}) == {"min": 20000, "max": 30000}
    sprinkler = price_item("fire_sprinkler", 2000)  # $3-7 per sq ft
    assert (sprinkler.min, sprinkler.max) == (6000, 14000)


def test_unknown_cost_item():
    with pytest.raises(UnknownCostItem):
        price_item("gold_faucets", 1)


def test_merge_needs_keeps_max_qty():
    merged = merge_needs([CostNeed("restroom_add", 1, "a"), CostNeed("restroom_add", 2, "b"), CostNeed("hvac_rtu", 1, "c")])
    assert {n.item: n.qty for n in merged} == {"restroom_add": 2, "hvac_rtu": 1}


def test_no_work_costs_only_permits_and_rent():
    prop = make_property(rent=4800, ti_allowance_per_sqft=0, size_sqft=1800)
    est = estimate([], prop, RESTAURANT)
    assert list(est.breakdown) == ["permits_fees"]
    assert est.fit_out.model_dump() == {"min": 5000, "max": 10000}
    assert est.buildout_months.model_dump() == {"min": 2, "max": 3}
    assert est.cost_to_open.model_dump() == {"min": 5000 + 2 * 4800, "max": 10000 + 3 * 4800}
    assert est.first_year.min == est.cost_to_open.min + 12 * 4800
    assert est.first_year.max == est.cost_to_open.max + 12 * 4800


def test_soft_costs_ti_and_buildout():
    prop = make_property(rent=4000, ti_allowance_per_sqft=10, size_sqft=2000)
    est = estimate([CostNeed("kitchen_install", 1, "none"), CostNeed("restroom_add", 1, "short")], prop, RESTAURANT)
    hard_min, hard_max = 40000 + 10000, 60000 + 15000
    assert est.hard_costs.model_dump() == {"min": hard_min, "max": hard_max}
    gc_min, gc_max = hard_min * 0.10, hard_max * 0.20
    assert est.breakdown["general_conditions_pct"].model_dump() == {"min": round(gc_min), "max": round(gc_max)}
    assert est.breakdown["contingency_pct"].model_dump() == {
        "min": round((hard_min + gc_min) * 0.10), "max": round((hard_max + gc_max) * 0.20)
    }
    # line items, breakdown and fit-out all agree
    assert sum(i.min for i in est.line_items) == est.fit_out.min
    assert sum(r.max for r in est.breakdown.values()) == est.fit_out.max
    assert est.ti_allowance == 20000
    assert est.net_fit_out.min == est.fit_out.min - 20000
    # kitchen adds 1-2 months on top of the restaurant's 2-3
    assert est.buildout_months.model_dump() == {"min": 3, "max": 5}
    assert est.cost_to_open.min == est.net_fit_out.min + 3 * 4000
    assert est.first_year.min <= est.first_year.max


def test_ti_never_makes_net_fit_out_negative():
    prop = make_property(ti_allowance_per_sqft=100, size_sqft=2000)
    est = estimate([], prop, RESTAURANT)
    assert est.net_fit_out.model_dump() == {"min": 0, "max": 0}


def test_estimate_cost_convenience():
    assert estimate_cost(["kitchen_install", "grease_interceptor"], "restaurant") == (48000, 80000)
    lo, hi = estimate_cost(["fire_sprinkler"], size_sqft=1000)
    assert (lo, hi) == (3000, 7000)
    assert estimate_kitchen_cost(True) == (0.0, 0.0)
    assert estimate_kitchen_cost(False) == (40000, 60000)
