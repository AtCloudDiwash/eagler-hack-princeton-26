"""API integration tests via TestClient: every endpoint, error codes, SQLite round-trip, demo sanity."""
from __future__ import annotations

import pytest
from conftest import ALL_IDS, DEMO_DETAILS

from app.config import settings

DEMO_BODY = {
    "business_profile": {"type": "restaurant", "details": DEMO_DETAILS, "city": "Austin", "state": "TX"},
    "property_ids": ALL_IDS,
}

RESULT_KEYS = {
    "property_id", "address", "rank", "score", "disqualified", "disqualifiers", "monthly_rent",
    "total_cost_estimate", "first_year_cost", "fit_out_estimate", "ti_allowance", "buildout_months",
    "breakdown", "line_items", "compliance", "criteria_results", "questions_for_landlord", "landlord_request",
    "observations", "media", "assumptions",
}
REQUIREMENT_KEYS = {
    "business_type", "business_label", "city", "state", "capacity", "capacity_unit", "occupant_load",
    "parking_required", "parking_source", "bathrooms_required", "min_sqft", "max_sqft", "max_rent",
    "needs_kitchen", "required_hvac_tons", "required_electrical_amps", "assumptions",
}


@pytest.fixture(scope="module")
def demo(client):
    response = client.post("/api/v1/analyze", json=DEMO_BODY)
    assert response.status_code == 200, response.text
    return response.json()


def test_health(client, monkeypatch):
    body = client.get("/health").json()
    assert body == {"status": "ok", "mode": {"costar": "mock", "matterport": "mock", "vexcel": "mock", "parser": "regex"}}
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    assert client.get("/health").json()["mode"]["parser"] == "claude"


def test_business_types(client):
    types = client.get("/api/v1/business-types").json()
    restaurant = next(t for t in types if t["id"] == "restaurant")
    assert restaurant == {"id": "restaurant", "label": "Restaurant", "capacity_unit": "seats",
                          "default_capacity": 40, "needs_kitchen": True}
    assert any(t["id"] == "dental_clinic" for t in types)


def test_criteria(client):
    all_criteria = client.get("/api/v1/criteria").json()
    restaurant = client.get("/api/v1/criteria", params={"business_type": "restaurant", "city": "Austin", "state": "TX"}).json()
    assert len(restaurant) < len(all_criteria)
    assert set(restaurant[0]) == {
        "id", "description", "domain", "weight", "hard_block", "evaluator", "required_inputs", "missing_data_policy",
        "evidence_required", "source", "thresholds", "business_types", "applicable_jurisdictions",
    }
    assert "window_visibility" in {c["id"] for c in restaurant}
    assert client.get("/api/v1/criteria", params={"business_type": "spaceport"}).status_code == 400


def test_properties(client):
    props = client.get("/api/v1/properties", params={"city": "Austin"}).json()
    assert {p["id"] for p in props} == set(ALL_IDS)
    assert props[0]["image_url"].startswith("/static/properties/")
    assert {"zoning", "previous_use", "ti_allowance_per_sqft", "latitude", "longitude", "matterport_url", "available"} <= set(props[0])
    assert [p["id"] for p in client.get("/api/v1/properties", params={"city": "78702"}).json()] == ["property-456", "property-321"]
    assert all(p["rent"] <= 4000 for p in client.get("/api/v1/properties", params={"budget": 4000}).json())
    sized = client.get("/api/v1/properties", params={"min_size": 1700, "max_size": 2100}).json()
    assert {p["id"] for p in sized} == {"property-123", "property-456"}
    assert client.get("/api/v1/properties", params={"city": "Princeton"}).json() == []
    assert client.get("/api/v1/properties", params={"business_type": "spaceport"}).status_code == 400


def test_analyze_errors(client):
    body = {**DEMO_BODY, "property_ids": []}
    assert client.post("/api/v1/analyze", json=body).status_code == 422
    bad_type = {**DEMO_BODY, "business_profile": {**DEMO_BODY["business_profile"], "type": "spaceport"}}
    response = client.post("/api/v1/analyze", json=bad_type)
    assert response.status_code == 400 and "spaceport" in response.json()["detail"]
    response = client.post("/api/v1/analyze", json={**DEMO_BODY, "property_ids": ["property-999"]})
    assert response.status_code == 404 and "property-999" in response.json()["detail"]
    assert client.post("/api/v1/analyze", json={"property_ids": ["property-123"]}).status_code == 422


def test_analyze_response_shape(demo):
    assert set(demo) == {"analysis_id", "created_at", "business_type", "requirements", "ranking_basis", "results", "mode", "disclaimer"}
    assert len(demo["analysis_id"]) == 32 and demo["created_at"].endswith("Z")
    assert set(demo["requirements"]) == REQUIREMENT_KEYS
    assert demo["mode"] == {"costar": "mock", "matterport": "mock", "vexcel": "mock", "parser": "regex"}
    assert demo["disclaimer"].startswith("Preliminary estimates")
    for result in demo["results"]:
        assert set(result) == RESULT_KEYS
        assert set(result["media"]) == {"aerial_url", "floor_plan_url", "matterport_embed_url", "image_url"}
        for rng in ("total_cost_estimate", "first_year_cost", "fit_out_estimate", "buildout_months"):
            assert result[rng]["min"] <= result[rng]["max"]
        assert set(result["compliance"]) == {c["id"] for c in result["criteria_results"]}
        for c in result["criteria_results"]:
            assert c["status"] in {"PASS", "RISK", "UNKNOWN"}
            assert (c["score"] is None) == (not c["counted"])
            for ev in c["evidence"]:
                assert ev["source"] in {"costar", "matterport", "vexcel", "requirements", "jurisdiction"}
        assert sum(i["min"] for i in result["line_items"]) == result["fit_out_estimate"]["min"]
        assert result["landlord_request"].startswith("Subject:")
    assert [r["rank"] for r in demo["results"]] == [1, 2, 3, 4]


def test_demo_ranking_is_explainable(demo):
    results = {r["property_id"]: r for r in demo["results"]}
    top = demo["results"][0]
    assert top["property_id"] == "property-456"
    assert top["score"] == 100.0 and not top["disqualified"]
    assert all(v["status"] == "PASS" for v in top["compliance"].values())

    lo = results["property-789"]
    assert lo["disqualified"] and lo["disqualifiers"] == ["zoning_use"]
    assert demo["results"][-1]["property_id"] == "property-789"  # disqualified last
    assert "does not permit" in lo["compliance"]["zoning_use"]["notes"]

    qualified = [r for r in demo["results"] if not r["disqualified"]]
    assert [r["first_year_cost"]["min"] for r in qualified] == sorted(r["first_year_cost"]["min"] for r in qualified)
    assert "first-year cost" in demo["ranking_basis"]

    # Retail space without a kitchen needs a full kitchen build-out
    r123 = results["property-123"]
    assert "kitchen_install" in r123["breakdown"]
    assert r123["compliance"]["parking_sufficiency"]["status"] == "RISK"
    assert r123["ti_allowance"] == 20000
    assert any("TI allowance" in q for q in r123["questions_for_landlord"])

    # Evidence boxes overlay the right image
    parking_ev = r123["observations"]["visible_parking_count"]
    assert parking_ev["source"] == "vexcel" and parking_ev["box"]
    assert r123["media"]["aerial_url"] == "/static/aerials/property-123.svg"


def test_analyses_round_trip(client, demo):
    listing = client.get("/api/v1/analyses").json()
    row = next(r for r in listing if r["analysis_id"] == demo["analysis_id"])
    assert row == {
        "analysis_id": demo["analysis_id"], "created_at": demo["created_at"], "business_type": "restaurant",
        "business_label": "Restaurant", "city": "Austin", "state": "TX", "property_count": 4,
        "top_property_id": "property-456", "top_address": "456 Oak Avenue",
    }
    stored = client.get(f"/api/v1/analyses/{demo['analysis_id']}")
    assert stored.status_code == 200
    assert stored.json() == demo  # exactly what POST returned
    assert client.get("/api/v1/analyses/doesnotexist").status_code == 404


def test_analyses_newest_first_and_limit(client):
    ids = []
    for pid in ("property-123", "property-456"):
        body = {**DEMO_BODY, "property_ids": [pid]}
        ids.append(client.post("/api/v1/analyze", json=body).json()["analysis_id"])
    listing = client.get("/api/v1/analyses", params={"limit": 2}).json()
    assert [r["analysis_id"] for r in listing] == ids[::-1]
    assert client.get("/api/v1/analyses", params={"limit": 0}).status_code == 422


def test_static_media_served(client, demo):
    for result in demo["results"]:
        for key in ("aerial_url", "floor_plan_url", "image_url"):
            url = result["media"][key]
            response = client.get(url)
            assert response.status_code == 200, url
            assert "svg" in response.headers["content-type"]


def test_cors_allows_frontend(client):
    response = client.options("/api/v1/properties", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET",
    })
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_criteria_config_error_returns_clear_500(client, monkeypatch, tmp_path):
    bad = tmp_path / "broken.yaml"
    bad.write_text("- id: broken\n  description: x\n  domain: space\n")
    monkeypatch.setattr(settings, "criteria_path", bad)
    response = client.get("/api/v1/criteria")
    assert response.status_code == 500 and "broken" in response.json()["detail"]
