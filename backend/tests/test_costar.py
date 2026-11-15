"""CoStar integration tests with a synthetic index: matching a building to its CoStar record, rentable area,
spaces that fit the user's size, net asking rent feeding the cost engine, and listed properties added to search."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import pytest  # noqa: E402

from services import costar, costs, program  # noqa: E402
from services.intent import parse_rules  # noqa: E402

PROPS = [
    {"id": 1, "lat": 29.7600, "lon": -95.3700, "address": "100 Main St, Houston, TX", "name": "Main Plaza", "type": "GeneralRetail",
     "rentable_sqft": 24000, "rentable_basis": "GLA", "gross_sqft": 25000, "typical_floor_sqft": 25000, "stories": 1, "lot_sqft": 80000,
     "year_built": None, "parking_ratio": 4.0, "matterport_models": ["TestScan123"],
     "lease_listings": [{"listing_id": 9, "status": 1, "total_available_sqft": 5200, "min_divisible_sqft": None, "max_contiguous_sqft": None, "spaces": [
         {"suite": "105", "floor": "1", "sqft_min": 1800, "sqft_max": 1800, "rate_low": 28, "rate_high": 30, "rate_basis": "yearly", "service": "TripleNet", "use": "Retail", "lease_pending": False, "available_on": None},
         {"suite": "110", "floor": "1", "sqft_min": 3400, "sqft_max": 3400, "rate_low": 2.5, "rate_high": 2.5, "rate_basis": "monthly", "service": "FullService", "use": "Retail", "lease_pending": False, "available_on": None},
     ]}]},
    {"id": 2, "lat": 29.7700, "lon": -95.3800, "address": "5 Tower Rd, Houston, TX", "name": None, "type": "Office", "rentable_sqft": 90000, "rentable_basis": "RBA",
     "gross_sqft": 95000, "typical_floor_sqft": 15000, "stories": 6, "lot_sqft": 40000, "year_built": None, "parking_ratio": None, "matterport_models": [], "lease_listings": []},
]


@pytest.fixture(autouse=True)
def index(tmp_path, monkeypatch):
    path = tmp_path / "costar_index.json"
    path.write_text(json.dumps({"properties": PROPS}))
    monkeypatch.setattr(costar, "INDEX", path)
    costar._index.cache_clear()
    yield
    costar._index.cache_clear()


def test_match_inside_footprint_or_nearby():
    square = {"type": "Polygon", "coordinates": [[[-95.3702, 29.7598], [-95.3698, 29.7598], [-95.3698, 29.7602], [-95.3702, 29.7602], [-95.3702, 29.7598]]]}
    assert costar.match(29.7600, -95.3700, square)["match"] == "inside footprint"
    assert costar.match(29.76025, -95.37, None)["id"] == 1  # ~28 m away
    assert costar.match(29.7650, -95.3750, None) is None  # nothing within 50 m


def test_summary_rentable_area_and_fitting_spaces():
    s = costar.summarize(costar.match(29.76, -95.37), need_min=1500, need_max=2200)
    assert s["rentable_sqft"] == 24000 and s["rentable_basis"] == "GLA"
    assert s["available_sqft"] == 5200 and [f["suite"] for f in s["fitting_spaces"]] == ["105"]
    assert s["asking_rent_per_sqft_yr"] == [30.0, 30.0]  # $2.50/month normalised to $30/yr


def test_listed_spaces_drive_size_check_and_rent():
    p = program.build(parse_rules("restaurant with 50 seats in Houston"))  # ~1,750 sq ft: suite 105 fits
    fields = costar.candidate_fields(costar.match(29.76, -95.37), p["size"]["min_sqft"], p["size"]["max_sqft"], p["size"]["target_sqft"])
    assert fields["best_space"]["suite"] == "105" and fields["best_space"]["service"] == "TripleNet"
    check = next(c for c in program.site_checks(p, program.facts_from(fields, None)) if c["id"] == "size")
    assert check["status"] == "pass" and "Suite 105" in check["detail"]
    est = costs.estimate("restaurant", 1800, "houston-tx", [], rent_override={"per_sqft_low": 30, "per_sqft_high": 30, "source": "CoStar listing, Suite 105, TripleNet"})
    assert any("CoStar" in a for a in est["assumptions"])


def test_closest_listed_suite_drives_size_when_none_fit():
    """A real vacancy remains the size basis even when it is too large for the program."""
    fields = costar.candidate_fields(costar.match(29.76, -95.37), 1000, 1200, 1100)
    assert fields["best_space"]["suite"] == "105"
    assert fields["best_space"]["sqft"] == 1800

    p = program.build(parse_rules("restaurant between 1000 and 1200 sq ft in Houston"))
    check = next(c for c in program.site_checks(p, program.facts_from(fields, None)) if c["id"] == "size")
    assert check["status"] == "risk"
    assert "Suite 105" in check["detail"] and "1,800 rentable sq ft" in check["detail"]


def test_listed_near_filters_by_type_and_listing():
    assert [p["id"] for p in costar.listed_near(29.76, -95.37, 800, ["GeneralRetail"])] == [1]
    assert costar.listed_near(29.76, -95.37, 800, ["Office"]) == []  # the office tower has no spaces listed


def test_ground_floor_suites_preferred_for_street_level_uses():
    assert costar.is_ground_floor("First Floor") and costar.is_ground_floor("Ground") and costar.is_ground_floor("Lobby")
    assert costar.is_ground_floor("Nineteenth Floor") is False and costar.is_ground_floor("Mezzanine") is False and costar.is_ground_floor(None) is None
    upper = {**PROPS[0], "id": 3, "lease_listings": [{"listing_id": 1, "status": 1, "total_available_sqft": 3600, "min_divisible_sqft": None, "max_contiguous_sqft": None, "spaces": [
        {"suite": "1975", "floor": "Nineteenth Floor", "sqft_min": 1750, "sqft_max": 1750, "rate_low": 26, "rate_high": 26, "rate_basis": "yearly", "service": "TripleNet", "use": "Office", "lease_pending": False, "available_on": None},
        {"suite": "120", "floor": "First Floor", "sqft_min": 1650, "sqft_max": 1650, "rate_low": 30, "rate_high": 30, "rate_basis": "yearly", "service": "TripleNet", "use": "Retail", "lease_pending": False, "available_on": None}]}]}
    assert costar.candidate_fields(upper, 1500, 2200, 1750, ground_floor=True)["best_space"]["suite"] == "120"
    assert costar.candidate_fields(upper, 1500, 2200, 1750)["best_space"]["suite"] == "1975"  # closest size when floor doesn't matter
    p = program.build(parse_rules("restaurant with 50 seats in Houston"))
    only_upper = {**upper, "lease_listings": [{**upper["lease_listings"][0], "spaces": upper["lease_listings"][0]["spaces"][:1]}]}
    fields = costar.candidate_fields(only_upper, p["size"]["min_sqft"], p["size"]["max_sqft"], p["size"]["target_sqft"], ground_floor=True)
    gf = next(c for c in program.site_checks(p, program.facts_from(fields, None)) if c["id"] == "ground_floor")
    assert gf["status"] == "risk" and "nineteenth floor" in gf["detail"]


def test_older_index_records_still_summarize():
    """Records without the newer building keys (an index built before them) keep working, with None/fallbacks."""
    s = costar.summarize(costar.match(29.76, -95.37))
    assert s["matterport_models"] == ["TestScan123"] and s["matterport_scans"] == [{"id": "TestScan123", "caption": None}]
    assert s["building_class"] is None and s["sprinklers"] is None and s["listing_condition"] is None
    fields = costar.candidate_fields(costar.match(29.76, -95.37), 1500, 2200, 1800)
    assert fields["stories"] == 1 and fields["gross_sqft"] == 25000 and fields["parking_ratio"] == 4.0


def test_selection_survives_another_search_and_drives_panel(monkeypatch):
    from schemas import Intent
    from services import fit_summary
    rec = costar.match(29.76, -95.37)
    intent = Intent(sqft=3400)
    chosen = costar.candidate_fields(rec, 3000, 4000, 3400)["best_space"]
    assert chosen["suite"] == "110" and chosen["listing_id"] == 9
    # Another search overwrote the stored building with Suite 105.
    stored = {"id": "test", "lat": 29.76, "lon": -95.37, **costar.candidate_fields(rec, 1500, 2000, 1800)}
    resolved = costar.selected_fields(stored, Intent(sqft=1800), chosen)
    assert resolved["best_space"]["suite"] == "110"
    tiles = fit_summary.tiles(resolved, None, intent)
    assert next(t for t in tiles if t["id"] == "space")["sub"] == "Suite 110"
    assert "3,400 sq ft" in next(t for t in tiles if t["id"] == "monthly")["hint"]
    with pytest.raises(ValueError, match="no longer available"):
        costar.selected_fields(stored, intent, {**chosen, "listing_id": 999})


def test_pending_leases_do_not_supply_an_available_space():
    from copy import deepcopy

    rec = deepcopy(PROPS[0])
    for listing in rec["lease_listings"]:
        for space in listing["spaces"]:
            space["lease_pending"] = True
    fields = costar.candidate_fields(rec, 1500, 4000, 1800)
    assert fields["space_count"] == 2
    assert fields["best_space"] is None


def test_divisible_suite_uses_requested_portion_not_maximum_area():
    from copy import deepcopy

    rec = deepcopy(PROPS[0])
    rec['lease_listings'][0]['spaces'] = [{**rec['lease_listings'][0]['spaces'][0], 'suite': 'Ground retail', 'sqft_min': 500, 'sqft_max': 10000}]
    fields = costar.candidate_fields(rec, 970, 1280, 1110, True)
    assert fields['best_space']['sqft'] == 1110
    assert fields['best_space']['sqft_max'] == 10000
    assert fields['best_space']['suite'] == 'Ground retail'


def test_suggested_portion_survives_selection_and_drives_cost_tiles(monkeypatch):
    from copy import deepcopy
    from schemas import Intent
    from services import fit_summary

    rec = deepcopy(PROPS[0])
    rec['lease_listings'][0]['spaces'] = [{**rec['lease_listings'][0]['spaces'][0], 'suite': 'Ground floor retail', 'sqft_min': 500, 'sqft_max': 10000}]
    monkeypatch.setattr(costar, 'match', lambda *args: rec)
    intent = Intent(sqft=1200)
    fields = costar.candidate_fields(rec, 1000, 1500, 1200, True)
    prop = {'id': 'divisible', 'lat': 29.76, 'lon': -95.37, **fields}
    resolved = costar.selected_fields(prop, intent, fields['best_space'])
    tiles = fit_summary.tiles(resolved, None, intent)
    space = next(t for t in tiles if t['id'] == 'space')
    monthly = next(t for t in tiles if t['id'] == 'monthly')
    assert space['value'] == '1,200 sq ft' and space['sub'] == 'Ground floor retail'
    assert '10,000' in space['hint'] and 'landlord confirmation' in space['hint']
    assert '1,200 sq ft' in monthly['hint']
    # Below the advertised minimum, suggest the minimum with the same division caveat.
    prop = costar.selected_fields(prop, Intent(sqft=300), fields['best_space'])
    assert next(t for t in fit_summary.tiles(prop, None, Intent(sqft=300)) if t['id'] == 'space')['value'] == '500 sq ft'


@pytest.mark.parametrize("bounds,target", [((2180, 2180), 2180), ((500, 10000), 1200)])
def test_property_detail_keeps_suggested_suite_first_in_leasing_list(monkeypatch, bounds, target):
    """The same suite and proposed area must survive the summary's 20-row limit."""
    from copy import deepcopy
    from main import _detail
    from schemas import Intent

    rec = deepcopy(PROPS[0])
    template = rec["lease_listings"][0]["spaces"][0]
    chosen = {**template, "suite": "3445", "sqft_min": bounds[0], "sqft_max": bounds[1]}
    rec["lease_listings"] = [{**rec["lease_listings"][0], "spaces": [
        {**template, "suite": f"Other {i}", "sqft_min": 600 + i * 10, "sqft_max": 600 + i * 10}
        for i in range(24)
    ] + [chosen]}]
    monkeypatch.setattr(costar, "match", lambda *args: rec)
    intent = Intent(sqft=target)
    selection = {"listing_id": rec["lease_listings"][0]["listing_id"], "suite": "3445", "floor": chosen["floor"]}
    prop = costar.selected_fields({"id": "selected", "lat": 29.76, "lon": -95.37}, intent, selection)
    detail = _detail(prop, None, intent)
    tile = next(t for t in detail["highlights"] if t["id"] == "space")
    first = detail["costar"]["spaces"][0]
    assert first["suite"] == detail["best_space"]["suite"] == "3445"
    assert first["sqft"] == detail["best_space"]["sqft"] == target
    assert tile["value"] == f"{target:,} sq ft" and tile["sub"] == "Suite 3445"
    assert first["sqft_max"] == bounds[1]
    assert first["rent_per_sqft_yr"] == detail["best_space"]["rent_per_sqft_yr"]
    assert len(detail["costar"]["spaces"]) == 20
