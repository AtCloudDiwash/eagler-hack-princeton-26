"""Houston, TX: a no-zoning city with parking minimums (config/jurisdictions.yaml `houston-tx`).

Covers the config-driven zoning mode, recorded use restrictions, jurisdiction parking ratios with
market-based parking areas, and an end-to-end mock-mode analysis of the Houston sample listings."""
from __future__ import annotations

import pytest
from conftest import make_property, obs, profile

from app.config import business_types, jurisdiction_for
from app.providers import costar_provider
from app.services.compliance_engine import build_inputs, evaluate_criterion, run_compliance
from app.services.criteria_manager import applicable_criteria, get_criterion
from app.services.evaluators import HVAC_VERIFY_QUESTION, EvalContext
from app.services.requirements_parser import (
    build_requirements,
    code_parking_minimum,
    exempt_parking_area,
    property_parking_requirement,
)

HOUSTON_IDS = [f"property-hou-0{i}" for i in range(1, 6)]
RESTAURANT_RAW = {"capacity": 40, "bathrooms": 2, "parking": 20, "needs_kitchen": True}
HOUSTON = jurisdiction_for("Houston", "TX")
RESTAURANT = business_types()["restaurant"]


def houston_req(raw=None, business_type="restaurant"):
    raw = RESTAURANT_RAW if raw is None else raw
    return build_requirements(profile(business_type, city="Houston", state="TX"), raw)


def houston_prop(**overrides):
    data = dict(city="Houston", state="TX", zip="77008", zoning=None, use_restrictions=[])
    data.update(overrides)
    return make_property(**data)


def zoning_result(requirements, prop, jurisdiction=None):
    criterion = get_criterion("zoning_use")
    jurisdiction = jurisdiction or jurisdiction_for(prop.city, prop.state)
    business = business_types()[requirements.business_type]
    ctx = EvalContext(requirements, prop, {}, criterion, jurisdiction, business,
                      build_inputs(requirements, prop, {}, jurisdiction, business))
    return evaluate_criterion(criterion, ctx)


# ----------------------------- jurisdiction lookup -----------------------------


def test_houston_jurisdiction_lookup():
    rules = jurisdiction_for(" houston ", "tx")
    assert rules["key"] == "houston-tx" and rules["name"] == "Houston, TX"
    assert rules["zoning_mode"] == "none" and rules["zoning"] == {}
    assert "Ch. 10" in rules["zoning_source"]
    assert rules["parking_minimums"] is True
    assert rules["parking_ratios"] == {"restaurant": 10.0, "medical_office": 3.5}
    assert "§26-492" in rules["parking_ratio_source"]
    assert "2021 Uniform Plumbing Code" in rules["plumbing_code"]
    assert "25 TAC Ch. 228" in rules["health_code"]
    # inherited from `default`
    assert rules["use_restriction_blocks"]["no_food_service"] == ["restaurant"]
    # Austin keeps district zoning and its own citation
    austin = jurisdiction_for("Austin", "TX")
    assert austin["zoning_mode"] == "districts" and "Austin" in austin["zoning_source"]


def test_zoning_criterion_source_is_generic():
    criterion = get_criterion("zoning_use")
    assert "Austin" not in criterion.source and criterion.required_inputs == []


# ----------------------------- zoning / use restrictions -----------------------------


def test_no_zoning_city_passes_with_deed_restriction_note():
    result, outcome = zoning_result(houston_req(), houston_prop())
    assert result.status == "PASS" and not result.blocking
    assert "no zoning" in result.notes.lower() and "deed restrictions" in result.notes
    assert "Ch. 10" in result.source
    assert any(ev.key == "use_restrictions" and ev.source == "costar" for ev in result.evidence)
    assert any("deed restrictions" in q for q in outcome.questions)


def test_no_zoning_city_without_listing_disclosure_is_unknown():
    """evidence_required: nothing observed about restrictions -> not confirmed, never blocks."""
    result, _ = zoning_result(houston_req(), houston_prop(use_restrictions=None))
    assert result.status == "UNKNOWN" and not result.blocking and result.score is None


def test_use_restriction_disqualifies_in_houston():
    req = houston_req()
    prop = houston_prop(use_restrictions=["no_food_service"])
    result, outcome = zoning_result(req, prop)
    assert result.status == "RISK" and outcome.definitive_failure and result.blocking
    assert "no_food_service" in result.notes
    report = run_compliance(applicable_criteria("restaurant", "Houston", "TX"), req, prop, {}, HOUSTON, RESTAURANT)
    assert "zoning_use" in report.disqualifiers


def test_use_restriction_disqualifies_even_where_zoning_permits(restaurant_req):
    prop = make_property(zoning="GR", use_restrictions=["No_Food_Service"])  # Austin GR permits restaurants
    result, _ = zoning_result(restaurant_req, prop)
    assert result.status == "RISK" and result.blocking


def test_restriction_on_another_use_does_not_block():
    result, _ = zoning_result(houston_req(), houston_prop(use_restrictions=["no_medical"]))
    assert result.status == "PASS"
    dental = houston_req({"capacity": 4}, "dental_clinic")
    result, _ = zoning_result(dental, houston_prop(use_restrictions=["no_medical"]))
    assert result.status == "RISK" and result.blocking


# ----------------------------- parking -----------------------------


def test_parking_requirement_from_jurisdiction_ratio_with_citation():
    req = houston_req({"capacity": 40})  # parking not stated
    assert req.parking_source == "jurisdiction"
    assert req.parking_required == 14  # 10 per 1,000 sq ft x 1,400 sq ft (40 seats x 35 sq ft)
    assert any("§26-492" in a and "14 spaces" in a for a in req.assumptions)

    rule = code_parking_minimum(HOUSTON, "restaurant", 2000)
    assert (rule.spaces, rule.ratio, rule.exempt_area) == (20, 10.0, None)
    assert "§26-492" in rule.source and "20 spaces" in rule.note

    # per property: recomputed from its actual size; the user's number is a floor
    big = houston_prop(size_sqft=2400, latitude=29.8031865, longitude=-95.3997458)
    assert property_parking_requirement(req, big, HOUSTON, RESTAURANT)[0] == 24
    stated = houston_req()  # "20 parking spaces"
    assert stated.parking_source == "user" and stated.parking_required == 20
    assert property_parking_requirement(stated, big, HOUSTON, RESTAURANT)[0] == 24
    small = houston_prop(size_sqft=1500, latitude=29.8031865, longitude=-95.3997458)
    assert property_parking_requirement(stated, small, HOUSTON, RESTAURANT)[0] == 20

    dental = houston_req({"capacity": 4}, "dental_clinic")
    assert dental.parking_source == "jurisdiction" and dental.parking_required == 6  # 3.5 x 1,600 sq ft


def test_market_based_parking_district_has_no_minimum():
    eado = costar_provider.get_property("property-hou-04")  # 801 St Emanuel St, EaDo
    area = exempt_parking_area(HOUSTON, eado.latitude, eado.longitude)
    assert area and "EaDo" in area["name"]
    rule = code_parking_minimum(HOUSTON, "restaurant", eado.size_sqft, eado.latitude, eado.longitude)
    assert rule.spaces == 0 and "no parking minimum" in rule.note

    req = houston_req({"capacity": 40})
    required, _ = property_parking_requirement(req, eado, HOUSTON, RESTAURANT)
    assert required == 0
    inputs = build_inputs(req, eado, {}, HOUSTON, RESTAURANT)
    assert inputs["business_required_parking"] == 0 and inputs["code_required_parking"] == 0
    # a stated need still applies — the city just doesn't add a minimum on top
    assert property_parking_requirement(houston_req(), eado, HOUSTON, RESTAURANT)[0] == 20

    heights = costar_provider.get_property("property-hou-01")
    assert exempt_parking_area(HOUSTON, heights.latitude, heights.longitude) is None


def test_no_minimum_city_keeps_business_guideline():
    req = build_requirements(profile(), {"capacity": 40})  # Austin
    assert req.parking_source == "guideline" and req.parking_required == 14
    prop = make_property()
    inputs = build_inputs(req, prop, {}, jurisdiction_for("Austin", "TX"), RESTAURANT)
    assert inputs["business_required_parking"] == 14 and inputs["code_required_parking"] is None


# ----------------------------- end to end -----------------------------


def test_houston_listings(client):
    props = client.get("/api/v1/properties", params={"city": "Houston", "state": "TX"}).json()
    assert {p["id"] for p in props} == set(HOUSTON_IDS)
    assert all(p["zoning"] is None and p["listing_source"] == "sample" for p in props)
    assert all(p["latitude"] and p["longitude"] for p in props)
    assert next(p for p in props if p["id"] == "property-hou-03")["use_restrictions"] == ["no_food_service"]


HOUSTON_RESTAURANT_DETAILS = [
    "40 seats, kitchen needed, 2 bathrooms, 20 parking spaces",
    "40 seats, kitchen needed, 2 bathrooms",
]


def houston_restaurant_run(client, details):
    body = {
        "business_profile": {"type": "restaurant", "details": details, "city": "Houston", "state": "TX"},
        "property_ids": HOUSTON_IDS,  # all 5, including property-hou-05 (medical office / dental demo listing)
    }
    response = client.post("/api/v1/analyze", json=body)
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("details", HOUSTON_RESTAURANT_DETAILS)
def test_houston_restaurant_analysis(client, details):
    run = houston_restaurant_run(client, details)
    results = {r["property_id"]: r for r in run["results"]}
    assert set(results) == set(HOUSTON_IDS)

    restricted = results["property-hou-03"]
    assert restricted["disqualified"] and restricted["disqualifiers"] == ["zoning_use"]
    assert restricted["rank"] == len(HOUSTON_IDS)
    assert "no_food_service" in restricted["compliance"]["zoning_use"]["notes"]

    heights = results["property-hou-01"]  # second-gen restaurant: best fit
    assert not heights["disqualified"] and not heights["weak_fit"]
    assert heights["score"] == max(r["score"] for r in results.values())
    assert heights["compliance"]["zoning_use"]["status"] == "PASS"

    box = results["property-hou-02"]  # cheap retail box: full kitchen build-out
    assert any(item["item"] == "kitchen_install" for item in box["line_items"])
    assert box["first_year_cost"]["min"] > heights["first_year_cost"]["min"]

    eado = results["property-hou-04"]
    if run["requirements"]["parking_source"] == "jurisdiction":
        assert eado["compliance"]["parking_sufficiency"]["status"] == "PASS"  # no minimum in EaDo
    assert all(r["compliance"]["zoning_use"]["status"] == "PASS" for pid, r in results.items() if pid != "property-hou-03")

    # Every Houston listing's HVAC comes from building-level rooftop units prorated to the suite and
    # is short: verify-with-landlord, never priced, never scored.
    for r in results.values():
        hvac = next(c for c in r["criteria_results"] if c["id"] == "hvac_capacity")
        assert hvac["status"] == "UNKNOWN" and not hvac["counted"] and hvac["score"] is None
        assert not any(item["item"] == "hvac_rtu" for item in r["line_items"])
        assert HVAC_VERIFY_QUESTION in r["questions_for_landlord"]


@pytest.mark.parametrize("details", HOUSTON_RESTAURANT_DETAILS)
def test_houston_restaurant_top_pick(client, details):
    run = houston_restaurant_run(client, details)
    assert run["results"][0]["property_id"] == "property-hou-01"
    assert run["results"][0]["property_id"] != "property-hou-05"


# ----------------------------- parking wording / citation -----------------------------


def parking_result(requirements, prop, observations):
    criterion = get_criterion("parking_sufficiency")
    jurisdiction = jurisdiction_for(prop.city, prop.state)
    business = business_types()[requirements.business_type]
    ctx = EvalContext(requirements, prop, observations, criterion, jurisdiction, business,
                      build_inputs(requirements, prop, observations, jurisdiction, business))
    return evaluate_criterion(criterion, ctx)[0]


def test_parking_criterion_source_is_generic():
    assert "Austin" not in get_criterion("parking_sufficiency").source


def test_parking_jurisdiction_requirement_cites_houston_code():
    req = houston_req({"capacity": 40})  # parking not stated -> city minimum
    result = parking_result(req, houston_prop(size_sqft=1800), obs("vexcel", visible_parking_count=4))
    assert result.status == "RISK"
    assert "18 needed (Houston Code §26-492: 10 per 1,000 sq ft)" in result.notes
    assert "guideline" not in result.notes and "you stated" not in result.notes
    assert "§26-492" in result.source and "Austin" not in result.source
    rule = {e.key: e for e in result.evidence}
    assert rule["parking_rule"].source == "jurisdiction" and "§26-492" in rule["parking_rule"].note
    assert rule["code_required_parking"].value == 18 and rule["code_required_parking"].source == "jurisdiction"


def test_parking_city_minimum_raises_user_number():
    stated = houston_req()  # "20 parking spaces"
    raised = parking_result(stated, houston_prop(size_sqft=2400), obs("vexcel", visible_parking_count=22))
    assert raised.status == "RISK" and "vs 24 needed (you stated 20; Houston Code §26-492" in raised.notes
    assert "raises it to 24" in raised.notes
    below = parking_result(stated, houston_prop(size_sqft=1500), obs("vexcel", visible_parking_count=22))
    assert below.status == "PASS" and "(you stated; Houston Code §26-492 minimum is 15)" in below.notes


def test_parking_market_based_area_says_no_city_minimum():
    eado = costar_provider.get_property("property-hou-04")
    city_rule = parking_result(houston_req({"capacity": 40}), eado, obs("vexcel", visible_parking_count=0))
    assert city_rule.status == "PASS" and "No spaces required" in city_rule.notes
    assert "no Houston, TX parking minimum in the East Downtown (EaDo) market-based parking area" in city_rule.notes
    assert "§26-471" in city_rule.source
    stated = parking_result(houston_req(), eado, obs("vexcel", visible_parking_count=0))
    assert stated.status == "RISK" and "20 needed (you stated; no Houston, TX parking minimum" in stated.notes


def test_parking_guideline_wording_cites_austin_rule():
    austin = build_requirements(profile(), {"capacity": 40})  # Austin: no minimums -> guideline
    assert austin.parking_source == "guideline"
    result = parking_result(austin, make_property(), obs("vexcel", visible_parking_count=5))
    assert result.status == "RISK" and "(business guideline, not a code minimum)" in result.notes
    assert "Nov 2, 2023" in result.source
    rule = next(e for e in result.evidence if e.key == "parking_rule")
    assert rule.source == "jurisdiction" and "Nov 2, 2023" in rule.note


# ----------------------------- HVAC: building-level tons prorated to the suite -----------------------------


def hvac_eval(prop, observations, prorate=True):
    criterion = get_criterion("hvac_capacity")
    criterion = criterion.model_copy(update={"thresholds": {**criterion.thresholds, "prorate_by_footprint": prorate}})
    req = houston_req()
    jurisdiction, business = jurisdiction_for(prop.city, prop.state), business_types()["restaurant"]
    ctx = EvalContext(req, prop, observations, criterion, jurisdiction, business,
                      build_inputs(req, prop, observations, jurisdiction, business))
    return evaluate_criterion(criterion, ctx)


def hvac_result(prop, observations, prorate=True):
    return hvac_eval(prop, observations, prorate)[0]


EADO_HVAC = dict(hvac_tons=90, rooftop_hvac_units=18, building_footprint_sqft=35049)


def test_hvac_prorated_by_footprint():
    assert get_criterion("hvac_capacity").thresholds["prorate_by_footprint"] is True  # visible in config
    result = hvac_result(houston_prop(size_sqft=2400), obs("vexcel", **EADO_HVAC))
    share = next(e for e in result.evidence if e.key == "hvac_tons_suite_share")
    assert share.value == pytest.approx(round(90 * 2400 / 35049, 1)) == 6.2
    assert "your share of 18 rooftop units (35,049 sq ft building, 2,400 sq ft suite)" in share.note
    assert {"hvac_tons", "rooftop_hvac_units", "building_footprint_sqft"} <= {e.key for e in result.evidence}


def test_hvac_prorated_short_share_is_verify_unknown():
    """Prorated share below the need: UNKNOWN to verify with the landlord, excluded from the score
    (despite assume_risk), no new-unit cost, and a landlord question."""
    assert get_criterion("hvac_capacity").missing_data_policy == "assume_risk"
    result, outcome = hvac_eval(houston_prop(size_sqft=2400), obs("vexcel", **EADO_HVAC))
    assert result.status == "UNKNOWN" and outcome.verify
    assert result.counted is False and result.score is None
    assert result.notes == ("Building has 18 rooftop units (≈90 tons total); your prorated share ≈6.2 tons vs 12 "
                            "needed — ask the landlord which units serve your suite.")
    assert outcome.cost_items == []
    assert outcome.questions == [HVAC_VERIFY_QUESTION]


def test_hvac_verify_unknown_excluded_from_property_score():
    prop = houston_prop(size_sqft=2400)
    req = houston_req()
    jurisdiction, business = jurisdiction_for(prop.city, prop.state), business_types()["restaurant"]
    criteria = applicable_criteria("restaurant", "Houston", "TX")
    report = run_compliance(criteria, req, prop, obs("vexcel", **EADO_HVAC), jurisdiction, business)
    hvac = next(r for r in report.criteria_results if r.id == "hvac_capacity")
    assert hvac.status == "UNKNOWN" and not hvac.counted
    assert not any(n.item == "hvac_rtu" for n in report.cost_needs)
    assert HVAC_VERIFY_QUESTION in report.questions
    # the score is the same as if the criterion were not in the registry at all
    without = run_compliance([c for c in criteria if c.id != "hvac_capacity"], req, prop,
                             obs("vexcel", **EADO_HVAC), jurisdiction, business)
    assert report.score == without.score


def test_hvac_prorated_share_meeting_need_passes():
    result, outcome = hvac_eval(houston_prop(size_sqft=2400), obs("vexcel", hvac_tons=200, rooftop_hvac_units=40,
                                                                   building_footprint_sqft=35049))
    assert result.status == "PASS" and result.counted and not outcome.verify
    assert result.notes.startswith("≈13.7 tons of rooftop HVAC (your share of 40 rooftop units")


def test_hvac_zero_rooftop_units_is_risk_with_cost():
    result, outcome = hvac_eval(houston_prop(size_sqft=2400),
                                obs("vexcel", hvac_tons=0, rooftop_hvac_units=0, building_footprint_sqft=35049))
    assert result.status == "RISK" and result.counted and result.score == 0 and not outcome.verify
    assert result.notes.startswith("No rooftop HVAC units detected on the building vs 12 tons needed")
    assert [(n.item, n.qty) for n in outcome.cost_items] == [("hvac_rtu", 3)]


def test_hvac_direct_tonnage_shortfall_is_risk_with_cost():
    """Not prorated (footprint unknown): a short fixture value is the suite's own capacity -> RISK + cost."""
    result, outcome = hvac_eval(houston_prop(size_sqft=2400), obs("vexcel", hvac_tons=5))
    assert result.status == "RISK" and result.counted and not outcome.verify
    assert result.notes.startswith("5 tons of rooftop HVAC vs 12 tons needed")
    assert [(n.item, n.qty) for n in outcome.cost_items] == [("hvac_rtu", 2)]


def test_hvac_proration_toggle_and_small_building():
    off = hvac_result(houston_prop(size_sqft=2400), obs("vexcel", **EADO_HVAC), prorate=False)
    assert off.status == "PASS" and off.notes.startswith("90 tons of rooftop HVAC")
    assert "hvac_tons_suite_share" not in {e.key for e in off.evidence}
    whole = hvac_result(houston_prop(size_sqft=2400), obs("vexcel", hvac_tons=15, building_footprint_sqft=2000))
    assert "hvac_tons_suite_share" not in {e.key for e in whole.evidence}  # footprint not larger than suite
    assert whole.notes.startswith("15 tons of rooftop HVAC")


def test_austin_fixture_hvac_unchanged(client):
    """Austin fixtures give direct (non-prorated) tonnage: a shortfall stays RISK, scored, with unit cost."""
    body = {"business_profile": {"type": "restaurant", "details": "40 seats, kitchen needed, 2 bathrooms, 20 parking spaces",
                                 "city": "Austin", "state": "TX"}, "property_ids": ["property-123"]}
    result = client.post("/api/v1/analyze", json=body).json()["results"][0]
    hvac = next(c for c in result["criteria_results"] if c["id"] == "hvac_capacity")
    assert hvac["notes"].startswith(f"{result['observations']['hvac_tons']['value']:g} tons of rooftop HVAC vs")
    assert "hvac_tons_suite_share" not in {e["key"] for e in hvac["evidence"]}
    assert hvac["status"] == "RISK" and hvac["counted"] and hvac["score"] == 0
    assert any(item["item"] == "hvac_rtu" for item in result["line_items"])


# ----------------------------- AnalysisResult listing fields -----------------------------


def test_analysis_result_carries_listing_source_and_restrictions(client):
    body = {"business_profile": {"type": "restaurant", "details": "40 seats", "city": "Houston", "state": "TX"},
            "property_ids": ["property-hou-03", "property-123"]}
    results = {r["property_id"]: r for r in client.post("/api/v1/analyze", json=body).json()["results"]}
    assert results["property-hou-03"]["listing_source"] == "sample"
    assert results["property-hou-03"]["use_restrictions"] == ["no_food_service"]
    austin = costar_provider.get_property("property-123")
    assert results["property-123"]["listing_source"] == austin.listing_source
    assert results["property-123"]["use_restrictions"] == austin.use_restrictions
    from app.models import AnalysisResult

    assert AnalysisResult.model_fields["listing_source"].default is None  # older stored runs -> null
    assert AnalysisResult.model_fields["use_restrictions"].default is None


def test_grease_check_cites_the_city_rule(client):
    """The grease interceptor result cites the jurisdiction's grease_code, not another city's."""
    body = {"business_profile": {"type": "restaurant", "details": "40 seats, kitchen needed", "city": "Houston", "state": "TX"},
            "property_ids": ["property-hou-02"]}
    houston = client.post("/api/v1/analyze", json=body).json()["results"][0]["compliance"]["grease_interceptor"]
    assert "Ch. 47" in houston["source"] and "Austin" not in houston["source"]
    body["business_profile"].update(city="Austin")
    body["property_ids"] = ["property-123"]
    austin = client.post("/api/v1/analyze", json=body).json()["results"][0]["compliance"]["grease_interceptor"]
    assert "Austin Water" in austin["source"]
