"""Unit tests for each registered evaluator (called directly, inputs present)."""
from __future__ import annotations

import pytest
from conftest import make_criterion, make_ctx, make_property, obs

from app.config import business_types
from app.services.evaluators import base_zoning_district, check_window_visibility, get_evaluator, registered_evaluators
from app.services.criteria_manager import load_criteria


def run(name, requirements, observations=None, **kwargs):
    thresholds = kwargs.pop("thresholds", {})
    criterion = make_criterion(evaluator=name, thresholds=thresholds)
    ctx = make_ctx(criterion, requirements, observations=observations, **kwargs)
    return get_evaluator(name).func(ctx)


def test_every_criteria_yaml_evaluator_is_registered():
    names = {c.evaluator for c in load_criteria()}
    assert names <= set(registered_evaluators())


# ----------------------------- zoning -----------------------------

@pytest.mark.parametrize("code, known, expected", [
    ("CS-MU", {"CS", "CS-1"}, "CS"), ("CS-1-MU-CO", {"CS", "CS-1"}, "CS-1"), ("LR-V", {"LR"}, "LR"), ("gr", {"GR"}, "GR"),
])
def test_base_zoning_district(code, known, expected):
    assert base_zoning_district(code, known) == expected


@pytest.mark.parametrize("zoning, status, definitive", [
    ("CS-MU", "PASS", False), ("GR", "PASS", False), ("LR-V", "RISK", False), ("LO", "RISK", True),
])
def test_zoning_austin(restaurant_req, zoning, status, definitive):
    out = run("zoning_checker", restaurant_req, obs("costar", zoning_code=zoning), prop=make_property(zoning=zoning))
    assert out.status == status
    assert out.definitive_failure is definitive
    assert "Land Development Code" in out.source


def test_zoning_unlisted_district_and_no_table(restaurant_req):
    out = run("zoning_checker", restaurant_req, obs("costar", zoning_code="PUD"))
    assert out.status == "UNKNOWN"
    out = run("zoning_checker", restaurant_req, obs("costar", zoning_code="C-2"), city="Dallas", state="TX")
    assert out.status == "UNKNOWN" and "No zoning use table" in out.notes


# ----------------------------- parking / ADA -----------------------------

def test_parking(restaurant_req):
    assert run("parking_checker", restaurant_req, obs("vexcel", visible_parking_count=22), thresholds={"min_ratio": 1}).status == "PASS"
    out = run("parking_checker", restaurant_req, obs("vexcel", visible_parking_count=15), thresholds={"min_ratio": 1})
    assert out.status == "RISK" and "15" in out.notes and out.questions
    assert "Nov 2, 2023" in out.source  # Austin parking note cited
    assert run("parking_checker", restaurant_req, obs("vexcel", visible_parking_count=15), thresholds={"min_ratio": 0.75}).status == "PASS"


def test_ada(restaurant_req):
    ok = run("ada_checker", restaurant_req, obs(door_width_inches=36, step_free_entrance=True), thresholds={"min_width": 32})
    assert ok.status == "PASS" and not ok.cost_items
    narrow = run("ada_checker", restaurant_req, obs(door_width_inches=30, step_free_entrance=False), thresholds={"min_width": 32})
    assert narrow.status == "RISK"
    assert {c.item for c in narrow.cost_items} == {"door_widening", "entrance_ramp"}
    assert narrow.definitive_failure is False
    unknown_steps = run("ada_checker", restaurant_req, obs(door_width_inches=34), thresholds={"min_width": 32})
    assert unknown_steps.status == "PASS" and any("step-free" in q for q in unknown_steps.questions)


# ----------------------------- fit-out -----------------------------

def test_kitchen(restaurant_req):
    assert run("kitchen_checker", restaurant_req, obs(kitchen_equipment_visible=True, hood_present=True)).status == "PASS"
    none = run("kitchen_checker", restaurant_req, obs(kitchen_equipment_visible=False))
    assert none.status == "RISK" and [c.item for c in none.cost_items] == ["kitchen_install"]
    no_hood = run("kitchen_checker", restaurant_req, obs(kitchen_equipment_visible=True, hood_present=False))
    assert no_hood.status == "RISK" and [c.item for c in no_hood.cost_items] == ["hood_exhaust"]
    not_needed = restaurant_req.model_copy(update={"needs_kitchen": False})
    assert run("kitchen_checker", not_needed, obs(kitchen_equipment_visible=False)).status == "PASS"


def test_grease(restaurant_req):
    assert run("grease_checker", restaurant_req, obs(grease_interceptor_present=True)).status == "PASS"
    out = run("grease_checker", restaurant_req, obs(grease_interceptor_present=False))
    assert out.status == "RISK" and out.cost_items[0].item == "grease_interceptor"


def test_operatories():
    from conftest import profile
    from app.services.requirements_parser import build_requirements

    dental = build_requirements(profile("dental_clinic", "4 chairs"), {"capacity": 4})
    assert run("operatory_checker", dental, obs(plumbed_operatories=4)).status == "PASS"
    out = run("operatory_checker", dental, obs(plumbed_operatories=1))
    assert out.status == "RISK" and out.cost_items[0].qty == 3


def test_bathrooms(restaurant_req):
    assert run("bathroom_checker", restaurant_req, obs(bathrooms_visible=2)).status == "PASS"
    out = run("bathroom_checker", restaurant_req, obs(bathrooms_visible=1))
    assert out.status == "RISK" and out.cost_items[0].item == "restroom_add" and out.cost_items[0].qty == 1
    assert "Uniform Plumbing Code" in out.source


def test_hvac_uses_larger_of_need_and_space(restaurant_req):
    # 2000 sq ft / 200 sq ft per ton = 10 tons > the 7 tons from seat count
    out = run("hvac_checker", restaurant_req, obs("vexcel", hvac_tons=5), thresholds={"tons_per_unit": 5})
    assert out.status == "RISK" and out.cost_items[0].qty == 1
    out = run("hvac_checker", restaurant_req, obs("vexcel", hvac_tons=2), thresholds={"tons_per_unit": 5})
    assert out.cost_items[0].qty == 2
    assert run("hvac_checker", restaurant_req, obs("vexcel", hvac_tons=10), thresholds={"tons_per_unit": 5}).status == "PASS"


def test_electrical(restaurant_req):
    assert run("electrical_checker", restaurant_req, obs(electrical_service_amps=400)).status == "PASS"
    out = run("electrical_checker", restaurant_req, obs(electrical_service_amps=200))
    assert out.status == "RISK" and out.cost_items[0].item == "electrical_service_upgrade"


def test_fire_safety(restaurant_req):
    # Demo-size restaurant: below the A-2 trigger (5000 sq ft / 100 occupants)
    assert run("fire_safety_checker", restaurant_req, obs()).status == "PASS"
    big = make_property(size_sqft=6000)
    out = run("fire_safety_checker", restaurant_req, obs(sprinklered=False), prop=big)
    assert out.status == "RISK" and out.cost_items[0].item == "fire_sprinkler" and out.cost_items[0].qty == 6000
    assert out.definitive_failure is False  # retrofit is priced, not disqualifying
    assert run("fire_safety_checker", restaurant_req, obs(sprinklered=True), prop=big).status == "PASS"
    assert run("fire_safety_checker", restaurant_req, obs(), prop=big).status == "UNKNOWN"
    # Business type without a sprinkler rule
    no_rule = {k: v for k, v in business_types()["restaurant"].items() if k != "sprinkler_required_if"}
    assert run("fire_safety_checker", restaurant_req, obs(), prop=big, business=no_rule).status == "PASS"


def test_window_visibility(restaurant_req):
    assert check_window_visibility(35, 10)[0] == "PASS"
    assert check_window_visibility(6, 10)[0] == "RISK"
    out = run("check_window_visibility", restaurant_req, obs(window_area=6), thresholds={"min_area": 10})
    assert out.status == "RISK" and out.evidence[0].key == "window_area"
