"""Vexcel live integration: normalization, footprint box, disk cache, per-item fallback, key safety,
roof / parking / HVAC evaluators on Vexcel facts. No network: httpx.get is monkeypatched."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest

from app.config import settings
from app.models import AnalysisResult, Evidence, Media
from app.providers import costar_provider, vexcel_provider
from app.providers.vexcel_provider import footprint_box, normalize_property_extract
from app.services.agent_orchestrator import gather_observations
from app.services.compliance_engine import evaluate_criterion
from app.services.evaluators import get_evaluator
from scripts.snapshot_vexcel import dump_observations, merge_snapshot

from conftest import make_criterion, make_ctx, make_property, obs

FIXTURE = Path(__file__).parent / "fixtures" / "vexcel_property_extract.json"
LA_LON, LA_LAT = -118.2437, 34.0522
SECRET = "vx-SECRET-key-123"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


def la_extract() -> dict:
    return json.loads(FIXTURE.read_text())


def la_property(**overrides):
    fields = dict(id="la-test", city="Los Angeles", state="CA", zip="90012", latitude=LA_LAT, longitude=LA_LON)
    return make_property(**{**fields, **overrides})


# ----------------------------- normalization -----------------------------


def test_normalize_recorded_la_extract():
    facts = normalize_property_extract(la_extract(), LA_LON, LA_LAT, tons_per_unit=5, sqft_per_space=350)
    values = {k: ev.value for k, ev in facts.items()}
    assert values == {
        "rooftop_hvac_units": 3, "hvac_tons": 15, "paved_area_sqft": 46039, "estimated_parking_spaces": 131,
        "roof_condition": 3, "roof_material": "membrane",
        "roof_defects": ["tarp", "discoloration", "structural-damage", "water-pooling"],
        "building_footprint_sqft": 73135, "building_footprint": 73135, "building_type": "commercial",
    }
    assert "vehicles_count" not in facts  # null in the response -> omitted so fixtures can fill it
    assert all(ev.source == "vexcel" and ev.live for ev in facts.values())
    assert facts["rooftop_hvac_units"].confidence == 0.93  # detection score
    assert facts["hvac_tons"].confidence < facts["rooftop_hvac_units"].confidence
    assert "estimated from 3 rooftop unit" in facts["hvac_tons"].note.lower()
    assert facts["estimated_parking_spaces"].confidence < 0.7 and "paved area" in facts["estimated_parking_spaces"].note
    assert "2026-07-03" in facts["roof_condition"].note


def test_normalize_uses_thresholds_and_nested_shape():
    facts = normalize_property_extract(la_extract(), LA_LON, LA_LAT, tons_per_unit=4, sqft_per_space=500)
    assert facts["hvac_tons"].value == 12 and facts["estimated_parking_spaces"].value == 92
    # nested keys normalize the same as Vexcel's flat dotted keys
    data = la_extract()
    s = data["features"][0]["properties"]["structures"][0]
    s["roof-objects"] = {"ac-unit": {"count": s.pop("roof-objects.ac-unit.count"), "score": s.pop("roof-objects.ac-unit.score")}}
    assert normalize_property_extract(data, LA_LON, LA_LAT)["rooftop_hvac_units"].value == 3


def test_normalize_empty_or_partial():
    assert normalize_property_extract({"features": []}, LA_LON, LA_LAT) == {}
    facts = normalize_property_extract(
        {"features": [{"properties": {"vehicles.count": 4, "vehicles.score": 0.8, "structures": []}}]}, LA_LON, LA_LAT
    )
    assert set(facts) == {"vehicles_count"} and facts["vehicles_count"].value == 4


# ----------------------------- footprint box -----------------------------


def _rect(west_m, south_m, east_m, north_m):
    """A rectangle ring given in metres from the LA point, as (lon, lat) vertices."""
    m_lat = 1 / 111_195.08
    m_lon = m_lat / 0.8285  # cos(34.05 deg)
    corners = [(west_m, south_m), (east_m, south_m), (east_m, north_m), (west_m, north_m), (west_m, south_m)]
    return [(LA_LON + e * m_lon, LA_LAT + n * m_lat) for e, n in corners]


def test_footprint_box_math():
    # a 20 m x 20 m square centred on the point covers the middle fifth of a 100 m image
    assert footprint_box([_rect(-10, -10, 10, 10)], LA_LON, LA_LAT, (100, 100)) == pytest.approx([0.4, 0.4, 0.2, 0.2], abs=2e-3)
    # north-east quadrant -> right half, top half (y grows downward on the image)
    assert footprint_box([_rect(0, 0, 40, 40)], LA_LON, LA_LAT) == pytest.approx([0.5, 0.1, 0.4, 0.4], abs=2e-3)
    # partly off-image -> clamped to the edge
    assert footprint_box([_rect(20, -10, 200, 10)], LA_LON, LA_LAT) == pytest.approx([0.7, 0.4, 0.3, 0.2], abs=2e-3)
    # union of a multipolygon's rings
    assert footprint_box([_rect(-40, 30, -30, 40), _rect(30, -40, 40, -30)], LA_LON, LA_LAT) == pytest.approx(
        [0.1, 0.1, 0.8, 0.8], abs=2e-3)
    # fully off-image or empty -> no box
    assert footprint_box([_rect(100, 0, 200, 10)], LA_LON, LA_LAT) is None
    assert footprint_box([], LA_LON, LA_LAT) is None


def test_footprint_clipped_before_bbox():
    # an L-shape whose far-west arm reaches north of the image top: only the visible part counts.
    # Visible: x in [-50, 20], y in [-20, 0] -> top edge at y=0 (0.5), not at the off-image arm.
    m_lat = 1 / 111_195.08
    m_lon = m_lat / 0.8285
    pts = [(-200, -20), (20, -20), (20, 0), (-60, 0), (-60, 80), (-200, 80), (-200, -20)]
    ring = [(LA_LON + e * m_lon, LA_LAT + n * m_lat) for e, n in pts]
    assert footprint_box([ring], LA_LON, LA_LAT) == pytest.approx([0.0, 0.5, 0.7, 0.2], abs=2e-3)


def test_recorded_footprint_box_matches_visible_roof():
    box = normalize_property_extract(la_extract(), LA_LON, LA_LAT)["building_footprint"].box
    # the building runs off the west and south edges of the 100 m image; its visible NE corner is
    # ~5.6 m east and ~7.8 m south of the point
    assert box == pytest.approx([0.0, 0.4222, 0.5562, 0.5778], abs=1e-3)
    assert all(0 <= v <= 1 for v in box) and box[0] + box[2] <= 1 and box[1] + box[3] <= 1


# ----------------------------- live calls: fakes -----------------------------


class FakeVexcel:
    """Stands in for httpx.get. `outcomes` maps item -> 'ok' | HTTP status | Exception."""

    def __init__(self, **outcomes):
        self.outcomes = {"ortho": "ok", "oblique": "ok", "property": "ok", **outcomes}
        self.calls: list[dict] = []

    def __call__(self, url, params=None, headers=None, timeout=None, **_):
        item = "ortho" if "/ortho/" in url else "oblique" if "/oriented/" in url else "property"
        self.calls.append({"item": item, "url": url, "params": params, "headers": headers, "timeout": timeout})
        outcome = self.outcomes[item]
        if isinstance(outcome, Exception):
            raise outcome
        request = httpx.Request("GET", url, params=params)
        if outcome != "ok":
            return httpx.Response(outcome, json={"message": "nope"}, request=request)
        if item == "property":
            return httpx.Response(200, json=la_extract(), request=request)
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"}, request=request)

    def items(self):
        return [c["item"] for c in self.calls]


@pytest.fixture
def vexcel_live(monkeypatch):
    monkeypatch.setattr(settings, "force_mock", False)
    monkeypatch.setattr(settings, "vexcel_api_key", SECRET)

    def install(**outcomes) -> FakeVexcel:
        fake = FakeVexcel(**outcomes)
        monkeypatch.setattr(httpx, "get", fake)
        return fake

    return install


# ----------------------------- cache -----------------------------


def test_cache_miss_then_hit(vexcel_live):
    fake = vexcel_live()
    prop = la_property()
    first = vexcel_provider.get_aerial(prop)
    assert sorted(fake.items()) == ["oblique", "ortho", "property"]
    assert first["aerial_url"] == "/static/vexcel-cache/la-test/ortho.jpg"
    assert first["oblique_url"] == "/static/vexcel-cache/la-test/oblique.jpg"
    assert first["aerial_source"] == "vexcel-live" and first["aerial_attribution"] == "© Vexcel Imaging US, Inc."
    assert first["live_observations"]["hvac_tons"].value == 15 and first["errors"] == {}
    folder = vexcel_provider.CACHE_DIR / "la-test"
    assert (folder / "ortho.jpg").read_bytes() == JPEG and (folder / "oblique.jpg").exists()
    assert json.loads((folder / "property.json").read_text())["features"]

    second = vexcel_provider.get_aerial(prop)
    assert len(fake.calls) == 3  # served from disk
    assert second["aerial_url"] == first["aerial_url"] and second["live_observations"] == first["live_observations"]

    vexcel_provider.get_aerial(prop, force_refresh=True)
    assert len(fake.calls) == 6
    vexcel_provider.get_aerial(la_property(latitude=29.7604, longitude=-95.3698))  # moved -> stale cache
    assert len(fake.calls) == 9


def test_request_shape_and_key_only_in_header(vexcel_live):
    fake = vexcel_live()
    vexcel_provider.get_aerial(la_property())
    for call in fake.calls:
        assert call["url"].startswith("https://api.vexcelgroup.com/v2/")
        assert call["headers"] == {"X-API-KEY": SECRET}
        assert SECRET not in call["url"] and SECRET not in json.dumps(call["params"])
        assert call["params"]["wkt"] == f"POINT({LA_LON} {LA_LAT})" and call["timeout"] == settings.provider_timeout_seconds
    by_item = {c["item"]: c["params"] for c in fake.calls}
    assert by_item["ortho"]["bbox-dimensions"] == "100,100" and by_item["ortho"]["layer"] == "urban"
    assert by_item["oblique"]["product-type"] == "oblique-n"
    assert by_item["property"]["unit-system"] == "imperial"


def test_cache_dir_name_is_sanitized(vexcel_live):
    vexcel_live()
    out = vexcel_provider.get_aerial(la_property(id="../../etc/passwd"))
    assert out["aerial_url"] == "/static/vexcel-cache/etc_passwd/ortho.jpg"
    assert (vexcel_provider.CACHE_DIR / "etc_passwd" / "ortho.jpg").exists()


# ----------------------------- per-item fallback -----------------------------


def test_property_404_keeps_live_imagery_and_fixture_facts(vexcel_live):
    fake = vexcel_live(property=404)
    prop = costar_provider.get_property("property-123")
    out = vexcel_provider.get_aerial(prop)
    assert out["aerial_source"] == "vexcel-live" and out["oblique_url"]
    assert out["live_observations"] == {} and "404" in out["errors"]["property"]
    assert out["observations"]["hvac_tons"]["value"] == 5  # fixture still there
    vexcel_provider.get_aerial(prop)
    assert len(fake.calls) == 3  # the 404 is remembered (meta.json), not re-requested


def test_geofence_403_falls_back_to_placeholders(vexcel_live):
    fake = vexcel_live(ortho=403, oblique=403, property=403)
    prop = costar_provider.get_property("property-123")  # Austin: outside the LA/Houston geofence
    out = vexcel_provider.get_aerial(prop)
    assert out["aerial_url"] == "/static/aerials/property-123.svg"
    assert out["aerial_source"] == "placeholder" and out["aerial_attribution"] is None and out["oblique_url"] is None
    assert out["errors"]["ortho"] == vexcel_provider.GEOFENCE_REASON
    vexcel_provider.clear_failure_cache()  # permanent failures survive a restart (stored on disk)
    vexcel_provider.get_aerial(prop)
    assert len(fake.calls) == 3


def test_timeout_is_transient(vexcel_live, monkeypatch):
    fake = vexcel_live(oblique=httpx.ReadTimeout("slow"))
    prop = la_property()
    out = vexcel_provider.get_aerial(prop)
    assert out["aerial_source"] == "vexcel-live" and out["oblique_url"] is None
    assert "timed out" in out["errors"]["oblique"] and out["live_observations"]
    vexcel_provider.get_aerial(prop)
    assert len(fake.calls) == 3  # inside the retry window
    monkeypatch.setattr(vexcel_provider, "TRANSIENT_RETRY_SECONDS", 0)
    fake.outcomes["oblique"] = "ok"
    out = vexcel_provider.get_aerial(prop)
    assert fake.items()[3:] == ["oblique"] and out["oblique_url"]  # only the failed item retried


def test_non_image_response_is_rejected(vexcel_live, monkeypatch):
    fake = vexcel_live()

    def html_ortho(url, **kw):
        if "/ortho/" in url:
            return httpx.Response(200, text="<html>login</html>", headers={"content-type": "text/html"},
                                  request=httpx.Request("GET", url))
        return fake(url, **kw)

    monkeypatch.setattr(httpx, "get", html_ortho)
    out = vexcel_provider.get_aerial(la_property())
    assert out["aerial_source"] == "placeholder" and "expected an image" in out["errors"]["ortho"]


def test_api_key_never_logged(vexcel_live, caplog):
    vexcel_live(ortho=RuntimeError(f"weird failure echoing header X-API-KEY: {SECRET}"),
                oblique=403, property=httpx.ConnectError(f"cannot connect {SECRET}"))
    with caplog.at_level(logging.DEBUG):
        out = vexcel_provider.get_aerial(la_property())
    assert caplog.records and "unavailable" in caplog.text
    assert SECRET not in caplog.text
    assert SECRET not in json.dumps(out["errors"])


def test_mock_mode_makes_no_calls(monkeypatch):
    monkeypatch.setattr(settings, "vexcel_api_key", SECRET)  # key set but USE_MOCK_DATA=true
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("network call in mock mode"))
    out = vexcel_provider.get_aerial(costar_provider.get_property("property-456"))
    assert out["aerial_source"] == "placeholder" and out["live_observations"] == {}


# ----------------------------- vision agent merge -----------------------------


def test_live_facts_override_fixture_facts(vexcel_live):
    vexcel_live()
    observations, media = gather_observations(costar_provider.get_property("property-123"))
    assert observations["hvac_tons"].value == 15 and observations["hvac_tons"].live  # fixture said 5
    assert observations["visible_parking_count"].value == 15 and not observations["visible_parking_count"].live
    assert observations["estimated_parking_spaces"].live and observations["building_footprint_sqft"].live
    assert "building_footprint" not in observations  # recorded LA outline is far off an Austin-centred image
    assert media.aerial_source == "vexcel-live" and media.aerial_attribution == "© Vexcel Imaging US, Inc."
    assert media.aerial_url == "/static/vexcel-cache/property-123/ortho.jpg"
    assert media.oblique_url == "/static/vexcel-cache/property-123/oblique.jpg"


def test_old_stored_runs_still_validate():
    assert Media.model_validate({"aerial_url": "/static/aerials/x.svg", "floor_plan_url": None,
                                 "matterport_embed_url": None, "image_url": None}).aerial_source == "placeholder"
    assert Evidence.model_validate({"key": "k", "value": 1, "source": "vexcel"}).live is False
    assert "live" in AnalysisResult.model_fields["observations"].annotation.__args__[1].model_fields


# ----------------------------- evaluators -----------------------------


def run(name, req, observations, **criterion_fields):
    criterion = make_criterion(evaluator=name, **criterion_fields)
    return get_evaluator(name).func(make_ctx(criterion, req, observations=observations))


def roof_obs(condition, defects=()):
    return obs("vexcel", roof_condition=condition, roof_defects=list(defects))


def test_roof_checker(restaurant_req):
    th = {"min_condition": 3}
    ok = run("roof_checker", restaurant_req, roof_obs(4), thresholds=th)
    assert ok.status == "PASS" and not ok.cost_items
    minor = run("roof_checker", restaurant_req, roof_obs(3, ["discoloration"]), thresholds=th)
    assert minor.status == "PASS" and "discoloration" in minor.notes
    worn = run("roof_checker", restaurant_req, roof_obs(2), thresholds=th)
    assert worn.status == "RISK" and worn.cost_items[0].item == "roof_repair"
    assert worn.cost_items[0].qty == 2000 and worn.definitive_failure is False  # suite size_sqft
    tarp = run("roof_checker", restaurant_req, roof_obs(5, ["tarp", "water-pooling"]), thresholds=th)
    assert tarp.status == "RISK" and "tarp" in tarp.notes and tarp.questions


def test_roof_missing_data_follows_policy(restaurant_req):
    c = make_criterion(id="roof_condition", evaluator="roof_checker", required_inputs=["roof_condition"],
                       missing_data_policy="unknown", evidence_required=True, thresholds={"min_condition": 3})
    result, outcome = evaluate_criterion(c, make_ctx(c, restaurant_req, observations={}))
    assert result.status == "UNKNOWN" and result.counted is False and not outcome.cost_items


def test_roof_on_recorded_la_facts_prices_repair(restaurant_req):
    facts = normalize_property_extract(la_extract(), LA_LON, LA_LAT)
    out = run("roof_checker", restaurant_req, facts, thresholds={"min_condition": 3})
    assert out.status == "RISK" and "structural damage" in out.notes and "tarp" in out.notes


def test_parking_falls_back_to_estimate(restaurant_req):  # restaurant_req needs 20 spaces
    th = {"min_ratio": 1}
    est = run("parking_checker", restaurant_req,
              obs("vexcel", estimated_parking_spaces=25, paved_area_sqft=8750), thresholds=th)
    assert est.status == "PASS" and "estimated" in est.notes and "paved area" in est.notes
    assert {e.key for e in est.evidence} >= {"estimated_parking_spaces", "paved_area_sqft"}
    short = run("parking_checker", restaurant_req, obs("vexcel", estimated_parking_spaces=10), thresholds=th)
    assert short.status == "RISK" and "estimated" in short.notes
    both = run("parking_checker", restaurant_req,
               obs("vexcel", visible_parking_count=15, estimated_parking_spaces=131), thresholds=th)
    assert both.status == "RISK" and "15 spaces visible" in both.notes  # striped count wins
    none = run("parking_checker", restaurant_req, {}, thresholds=th)
    assert none.status == "UNKNOWN" and none.questions


def test_parking_unknown_is_scored_as_risk_policy(restaurant_req):
    c = make_criterion(evaluator="parking_checker", required_inputs=["business_required_parking"],
                       missing_data_policy="assume_risk", evidence_required=True)
    result, _ = evaluate_criterion(c, make_ctx(c, restaurant_req, observations={}))
    assert result.status == "UNKNOWN" and result.counted and result.score == 0


def test_hvac_uses_live_tons(restaurant_req):
    facts = normalize_property_extract(la_extract(), LA_LON, LA_LAT)  # 15 tons from 3 units
    out = run("hvac_checker", restaurant_req, facts, thresholds={"tons_per_unit": 5})
    assert out.status == "PASS" and {"hvac_tons", "rooftop_hvac_units"} <= {e.key for e in out.evidence}


# ----------------------------- snapshot script helpers -----------------------------


def test_snapshot_merge_keeps_fixture_facts_and_format():
    observations = {"_comment": "x", "p1": {"aerial_url": "/a.svg", "aerial": {
        "visible_parking_count": {"value": 8, "confidence": 0.75, "note": "8 spaces"}}}}
    facts = normalize_property_extract(la_extract(), LA_LON, LA_LAT)
    merge_snapshot(observations, "p1", facts, "2026-11-14")
    merge_snapshot(observations, "p1", facts, "2026-11-14")  # idempotent
    aerial = observations["p1"]["aerial"]
    assert aerial["visible_parking_count"]["value"] == 8
    assert aerial["hvac_tons"]["value"] == 15 and aerial["hvac_tons"]["note"].startswith(
        "Snapshot of Vexcel property/extract on 2026-11-14")
    assert aerial["building_footprint"]["box"] and "box" not in aerial["hvac_tons"]
    text = dump_observations(observations)
    assert json.loads(text) == observations
    real = (Path(__file__).parent.parent / "fixtures" / "observations.json").read_text()
    assert dump_observations(json.loads(real)) == real  # rewriting never reformats the fixture
