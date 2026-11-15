"""Sizing and location tests: the size estimate (concepts, qualifiers, needs), the graded size fit (too small and
too big both score lower), the paged Vexcel sweep and the pre-screen's distance and size grading. Offline."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import pytest  # noqa: E402

from config import business_types  # noqa: E402
from services import discovery, program, sizing, vexcel  # noqa: E402
from services.intent import parse_rules  # noqa: E402

BAND = {"target_sqft": 1400, "min_sqft": 1210, "max_sqft": 1610}


def _size(query: str) -> dict:
    return program.build(parse_rules(query))["size"]


# ---------------------------------------------------------------- estimate

def test_every_business_has_exactly_one_default_concept_with_a_way_to_size_it():
    for key, cfg in business_types().items():
        concepts = cfg["program"].get("concepts", [])
        assert sum(1 for c in concepts if c.get("default")) == 1, key
        fields = {d["field"] for d in cfg["program"]["drivers"]}
        for c in concepts:
            assert c.get("default_sqft") or set(c.get("default_count", {})) & fields, (key, c["id"])
            for per in (c.get("sqft_per") or {}).values():
                assert len(per) == 3 and per[0] <= per[1] <= per[2], (key, c["id"])


def test_concept_changes_the_typical_size():
    coffee, full, fine = _size("coffee shop in Montrose"), _size("restaurant in Houston"), _size("fine dining restaurant in Houston")
    assert (coffee["concept"], full["concept"], fine["concept"]) == ("coffee_shop", "full_service", "fine_dining")
    assert coffee["target_sqft"] < full["target_sqft"] < fine["target_sqft"]
    assert _size("yoga studio in Montrose")["target_sqft"] < _size("gym in Houston")["target_sqft"]
    assert _size("boutique clothing store")["target_sqft"] < _size("furniture showroom")["target_sqft"]


def test_stated_count_drives_the_estimate_with_components():
    s = _size("40-seat restaurant in Houston")
    assert s["source"] == "derived" and s["min_sqft"] < s["target_sqft"] == 1400 < s["max_sqft"]
    assert sum(c["sqft"] for c in s["components"]) == pytest.approx(s["target_sqft"], abs=10)
    assert _size("dental office with 4 operatories")["target_sqft"] == 2000


def test_size_hint_scales_a_default_but_not_a_stated_count():
    assert _size("small cafe in Houston")["target_sqft"] < _size("cafe in Houston")["target_sqft"]
    assert _size("small 40-seat restaurant")["target_sqft"] == _size("40-seat restaurant")["target_sqft"]


def test_needs_that_take_floor_area_are_added():
    base, more = _size("60 seat restaurant in Houston"), _size("60 seat restaurant with private dining room and storage in Houston")
    assert more["target_sqft"] - base["target_sqft"] == 450


@pytest.mark.parametrize("query,expected", [
    ("2,400 sq ft restaurant", (2400, None, None)),
    ("at least 2,000 sq ft", (2000, 2000, None)),
    ("under 1.5k sf", (1500, None, 1500)),
    ("between 1,500 and 2,000 sq ft", (1750, 1500, 2000)),
    ("1-2k sq ft office", (1500, 1000, 2000)),
    ("200 seats and 3,000 sq ft restaurant", (3000, None, None)),  # not a range
    ("40 seats, $8k/month", (None, None, None)),
])
def test_size_qualifiers(query, expected):
    assert sizing.parse_size_request(query) == expected


def test_stated_bounds_are_exact():
    assert (_size("gym, at least 3,000 sq ft")["min_sqft"]) == 3000
    assert (_size("office under 2,000 sq ft for 10 people")["max_sqft"]) == 2000
    s = _size("restaurant between 1,500 and 2,000 sq ft")
    assert (s["min_sqft"], s["max_sqft"], s["source"]) == (1500, 2000, "stated")


def test_concept_earliest_keyword_wins():
    assert sizing.parse_concept("restaurant with a bar", "restaurant") == "full_service"
    assert sizing.parse_concept("wine bar with small plates", "restaurant") == "bar"
    assert sizing.parse_concept("dental office", "dental_clinic") == "dental"
    assert sizing.parse_concept("urgent care clinic", "dental_clinic") == "medical_clinic"


# ---------------------------------------------------------------- fit

def test_band_score_penalises_both_directions():
    assert sizing.band_score(1400, 1210, 1610) == 1
    assert sizing.band_score(950, 1210, 1610) < 0.5 and sizing.band_score(0.65 * 1210, 1210, 1610) == 0
    big = [sizing.band_score(a, 1210, 1610) for a in (2000, 3200, 6400, 50_000)]
    assert big == sorted(big, reverse=True) and big[0] > 0.8 and big[-1] == 0.05


def test_fit_footprint_too_big_and_too_small_score_lower():
    fits = sizing.fit(BAND, footprint_sqft=1500)
    big = sizing.fit(BAND, footprint_sqft=6000)
    huge = sizing.fit(BAND, footprint_sqft=60_000)
    small = sizing.fit(BAND, footprint_sqft=750)
    assert fits.status == "strong" and fits.check == "pass"
    assert big.score < fits.score and big.status == "weak" and huge.score <= big.score
    assert small.status == "weak" and small.score == 0
    assert sizing.fit(BAND) is None


def test_fit_listing_evidence():
    assert sizing.fit(BAND, best_space={"sqft": 1500, "suite": "100"}).status == "strong"
    divisible = sizing.fit(BAND, best_space={"sqft": 19_767, "sqft_min": 1000, "suite": "200"})
    assert divisible.status == "strong" and "1,000-19,767" in divisible.reason
    closest = sizing.fit(BAND, space_count=3, available_sqft=9000, closest_space_sqft=2600)
    assert closest.score <= 0.8 and "2,600" in closest.reason
    assert sizing.fit(BAND, interior_sqft=900).status == "weak"


def test_multi_floor_small_footprint_depends_on_ground_floor_need():
    assert sizing.fit(BAND, footprint_sqft=800, stories=2).status == "adequate"
    assert sizing.fit(BAND, footprint_sqft=800, stories=2, ground_floor_required=True).status == "weak"


# ---------------------------------------------------------------- location: the paged sweep

def _fake_pages(sizes: list[int]):
    def feature(page: int, i: int) -> dict:
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [page, i]}, "properties": {}}

    async def fake_get(path, params, expect_json=True):
        n = params["page"]
        if n > len(sizes):
            raise vexcel.VexcelError(400, "past the end")
        return {"features": [feature(n, i) for i in range(sizes[n - 1])]}
    return fake_get


def test_sweep_pages_until_a_short_page(monkeypatch):
    monkeypatch.setattr(vexcel.settings, "vexcel_api_key", "k")
    monkeypatch.setattr(vexcel, "_get", _fake_pages([500, 500, 500, 120]))
    features, complete = asyncio.run(vexcel.property_sweep(29.7, -95.4, 800))
    assert len(features) == 1620 and complete


def test_sweep_stops_at_max_pages_and_says_so(monkeypatch):
    monkeypatch.setattr(vexcel.settings, "vexcel_api_key", "k")
    monkeypatch.setattr(vexcel, "_get", _fake_pages([500] * 10))
    features, complete = asyncio.run(vexcel.property_sweep(29.7, -95.4, 800, max_pages=4))
    assert len(features) == 2000 and not complete


def test_sweep_exact_multiple_of_page_size_ends_cleanly(monkeypatch):
    monkeypatch.setattr(vexcel.settings, "vexcel_api_key", "k")
    monkeypatch.setattr(vexcel, "_get", _fake_pages([500, 500]))  # page 3 errors: past the end
    features, complete = asyncio.run(vexcel.property_sweep(29.7, -95.4, 800))
    assert len(features) == 1000 and complete


# ---------------------------------------------------------------- the pre-screen

def _building(**kw) -> dict:
    return {"id": "x", "lat": 29.7, "lon": -95.4, "building_type": "commercial", "area_sqft": 1500, "roof_condition": 4,
            "roof_condition_label": "Good", "stories_est": 1, "distance_m": 200, **kw}


def test_prescreen_prefers_near_over_far():
    intent = parse_rules("40-seat restaurant in Houston")
    prog = program.build(intent)
    near, _ = discovery.prescreen(_building(), intent, prog, None, "Montrose")
    far, reasons = discovery.prescreen(_building(distance_m=1400), intent, prog, None, "Montrose")
    assert near > far and any("1.4 km from Montrose" in r for r in reasons)


def test_prescreen_scores_too_big_and_too_small_lower():
    intent = parse_rules("40-seat restaurant in Houston")
    prog = program.build(intent)
    fit, _ = discovery.prescreen(_building(), intent, prog)
    big, big_reasons = discovery.prescreen(_building(area_sqft=12_000), intent, prog)
    small, _ = discovery.prescreen(_building(area_sqft=700), intent, prog)
    assert fit > big and fit > small and fit - big >= 20
    assert any(r.startswith("Size mismatch") for r in big_reasons)


@pytest.mark.parametrize("query,key,value", [
    ("office at least 1,234 sq ft", "min_sqft", 1234),
    ("office under 2,345 sq ft", "max_sqft", 2345),
])
def test_non_round_stated_bounds_are_exact(query, key, value):
    assert _size(query)[key] == value


def test_sweep_propagates_server_failure_on_later_page(monkeypatch):
    monkeypatch.setattr(vexcel.settings, "vexcel_api_key", "k")
    first = _fake_pages([500])

    async def failing_get(path, params):
        if params["page"] > 1:
            raise vexcel.VexcelError(503, "unavailable")
        return await first(path, params)

    monkeypatch.setattr(vexcel, "_get", failing_get)
    with pytest.raises(vexcel.VexcelError, match="unavailable"):
        asyncio.run(vexcel.property_sweep(29.7, -95.4, 800))


def test_locate_respects_explicit_state(monkeypatch):
    calls = []
    place = {"name": "Montrose", "lat": 38.48, "lon": -107.87, "addresstype": "city"}

    async def geocode(text):
        calls.append(text)
        return place

    monkeypatch.setattr(discovery.external, "geocode", geocode)
    assert asyncio.run(discovery.locate("Montrose, CO", [])) == place
    assert calls == ["Montrose, CO"]


def test_locate_disambiguates_neighborhood_with_a_note(monkeypatch):
    places = {
        "the Heights": {"name": "Heights", "display_name": "Heights County", "lat": 40, "lon": -100, "addresstype": "county"},
        "the Heights, Houston, TX": {"name": "Houston Heights", "lat": 29.8, "lon": -95.4},
    }

    async def geocode(text):
        return places.get(text)

    monkeypatch.setattr(discovery.external, "geocode", geocode)
    monkeypatch.setattr(discovery, "in_coverage", lambda lat, lon: lat == 29.8)
    notes = []
    place = asyncio.run(discovery.locate("the Heights", notes))
    assert place["name"] == "Houston Heights"
    assert notes and "Houston, TX" in notes[0]


def test_site_check_flags_oversized_building_but_accepts_fitting_suite():
    prog = program.build(parse_rules("40-seat restaurant in Houston"))
    facts = {"footprint_sqft": 60_000, "stories": 1}
    check = next(c for c in program.site_checks(prog, facts) if c["id"] == "size")
    assert check["status"] == "risk"
    facts["best_space"] = {"sqft": 1500, "suite": "100"}
    check = next(c for c in program.site_checks(prog, facts) if c["id"] == "size")
    assert check["status"] == "pass"
