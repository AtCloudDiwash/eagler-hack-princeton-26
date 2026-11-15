"""Building facts: the CoStar index builder's new fields (year built, sprinklers, parking, note flags) and the merged
CoStar + Vexcel facts() contract (precedence, second-generation use, unknowns omitted)."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import pytest  # noqa: E402

from config import FIXTURES_DIR  # noqa: E402
from services import building_facts as bf, costar  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_costar_index", Path(__file__).resolve().parents[1] / "scripts" / "build_costar_index.py")
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

ENUMS = {"BuildingClass": {"0": "Unknown", "1": "A", "2": "B", "3": "C"}, "ParkingType": {"0": "Unknown", "1": "Surface", "3": "Covered"},
         "PropertySubtype": {"18": "GeneralRetail_Restaurant", "64": "Office_Medical"}, "SprinklerType": {"1": "Wet"},
         "BuildingConstructionMaterialType": {"1": "Masonry"}}

SPACE = {"suite": "105", "floor": "First Floor", "sqft_min": 1800, "sqft_max": 1800, "rate_low": 30, "rate_high": 30, "rate_basis": "yearly",
         "service": "TripleNet", "use": "Retail", "lease_pending": False, "available_on": None}
STRIP = {"id": 11, "lat": 29.7600, "lon": -95.3700, "address": "100 Main St, Houston, TX", "name": "Main Plaza", "type": "GeneralRetail",
         "rentable_sqft": 24000, "rentable_basis": "GLA", "gross_sqft": 25000, "typical_floor_sqft": 25000, "stories": 2, "lot_sqft": 80000,
         "year_built": 1998, "parking_ratio": 4.0, "matterport_models": ["Scan1"], "matterport_scans": [{"id": "Scan1", "caption": "Suite 105"}],
         "building_class": "B", "sprinklers": False, "parking_spaces": 96, "parking_types": ["Surface"], "zoning": "C-2, Houston",
         "year_renovated": 2015, "renovated_systems": ["hvac", "roof"],
         "lease_listings": [{"listing_id": 9, "status": 1, "total_available_sqft": 5200, "min_divisible_sqft": None, "max_contiguous_sqft": None,
                             "condition": "Good", "spaces": [
             {**SPACE, "cam_per_sqft_yr": 6.5, "note_flags": ["restaurant", "second_generation"], "note_snippet": "2nd generation restaurant with hood and grease trap"},
             {**SPACE, "suite": "110", "sqft_min": 3400, "sqft_max": 3400, "prior_buildout": "Dental", "buildout_status": "FullBuildOut",
              "note_flags": ["medical"], "note_snippet": "Exam rooms"},
         ]}]}
BARE = {"id": 12, "lat": 29.7800, "lon": -95.3900, "address": "9 Empty Rd", "name": None, "type": "Office", "rentable_sqft": None, "rentable_basis": None,
        "gross_sqft": None, "typical_floor_sqft": None, "stories": None, "lot_sqft": None, "year_built": None, "parking_ratio": None,
        "matterport_models": [], "lease_listings": []}


def _feature(roof_height=None, ac_units=None, footprint=None, paved=None, condition=None) -> dict:
    s = {"primary-structure": True, "roof-characteristics.height": roof_height, "roof-objects.ac-unit.count": ac_units,
         "footprint.area": footprint, "roof-characteristics.condition": condition}
    return {"properties": {"structures": [{k: v for k, v in s.items() if v is not None}], **({"hardscapes.area": paved} if paved else {})}}


@pytest.fixture
def index(tmp_path, monkeypatch):
    path = tmp_path / "costar_index.json"
    path.write_text(json.dumps({"properties": [STRIP, BARE]}))
    monkeypatch.setattr(costar, "INDEX", path)
    costar._index.cache_clear()
    yield
    costar._index.cache_clear()


# ---------------------------------------------------------------- index builder

def test_year_built_comes_from_construction_events():
    raw = {"constructionEvents": [{"eventType": 1, "year": 1999}, {"eventType": 2, "year": 2001}, {"eventType": 4, "year": 2016}]}
    assert builder.year_built(raw) == 2001
    assert builder.year_built({"yearBuilt": 1950}) is None  # the kit has no yearBuilt field
    assert builder.building_fields(raw, ENUMS)["year_renovated"] == 2016


def test_builder_sprinklers_parking_and_placeholders():
    raw = {"hasSprinklers": False, "buildingClass": 2, "zoningDescription": "N/Ap, Houston", "propertySubtype": 18,
           "parking": [{"parkingType": 1, "totalSpaces": 40}, {"parkingType": 3, "totalSpaces": 10}, {"parkingType": 3, "totalSpaces": None}],
           "propertyOffice": {"structural": {"slabToSlabHeightFeet": 13, "elevators": [
               {"elevatorType": 1, "elevatorState": 1, "numElevators": 2}, {"elevatorType": 3, "elevatorState": 1}]}},
           "renovations": [{"endDate": "2019-05-01T00:00:00", "renovationImprovementTypes": [6, 8]}]}
    f = builder.building_fields(raw, ENUMS)
    assert f["sprinklers"] is False  # known "no" is kept, unlike unknown
    assert f["parking_spaces"] == 50 and f["parking_types"] == ["Covered", "Surface"]
    assert "zoning" not in f  # "N/Ap" placeholder dropped
    assert f["building_class"] == "B" and f["subtype"] == "GeneralRetail_Restaurant"
    assert f["elevators"] == 2 and f["has_elevator"] is True and f["slab_to_slab_ft"] == 13
    assert f["renovated_systems"] == ["hvac", "roof"] and f["year_renovated"] == 2019
    assert "sprinklers" not in builder.building_fields({"hasSprinklers": None}, ENUMS)


def test_builder_note_flags():
    flags, snippet = builder.note_flags(["Corner suite. 2nd generation restaurant with Type 1 hood and grease interceptor."])
    assert flags[0] == "restaurant" and "second_generation" in flags and "hood" in snippet
    assert builder.note_flags(["Reception, open area, kitchen and break room."])[0] == []  # an office kitchenette is not a restaurant
    assert builder.note_flags(["Fully built out dental suite with 3 exam rooms"])[0][:2] == ["dental", "medical"]


# ---------------------------------------------------------------- facts()

def test_costar_facts_for_the_chosen_space(index):
    prop = {"lat": 29.76, "lon": -95.37, "best_space": {"suite": "105", "sqft": 1800}}
    r = bf.facts(prop, None)
    f = r["facts"]
    assert r["costar_id"] == "11" and r["sources"] == ["CoStar"]
    assert bf.fact_value(r, "year_built") == 1998 and f["year_built"]["confidence"] == "high"
    assert bf.fact_value(r, "sprinklers") is False  # False is a known value, not omitted
    assert bf.fact_value(r, "parking_spaces") == 96 and f["parking_spaces"]["unit"] == "spaces"
    assert bf.fact_value(r, "zoning_code") == "C-2" and "C-2, Houston" in f["zoning_code"]["note"]
    assert bf.fact_value(r, "available_sqft") == 1800 and "Suite 105" in f["available_sqft"]["note"]
    assert bf.fact_value(r, "cam_per_sqft_yr") == 6.5
    assert bf.fact_value(r, "condition_rating") == "good"
    assert bf.fact_value(r, "renovated_systems") == ["hvac", "roof"] and bf.fact_value(r, "last_renovation_year") == 2015
    assert bf.fact_value(r, "second_generation_use") == "restaurant" and f["second_generation_use"]["confidence"] == "medium"
    for fact in f.values():
        assert set(fact) == {"value", "unit", "source", "confidence", "note"} and fact["value"] is not None


def test_prior_buildout_beats_listing_notes(index):
    r = bf.facts({"lat": 29.76, "lon": -95.37, "best_space": {"suite": "110", "sqft": 3400}}, None)
    assert bf.fact_value(r, "second_generation_use") == "dental"  # tenant build-out record outranks the "exam rooms" note
    assert r["facts"]["second_generation_use"]["confidence"] == "high"
    assert bf.fact_value(r, "prior_buildout_status") == "full"


def test_costar_wins_over_vexcel_and_vexcel_fills_gaps(index):
    feature = _feature(roof_height=65, ac_units=4, footprint=12000.4, paved=30000, condition=4)
    r = bf.facts({"lat": 29.76, "lon": -95.37}, feature)
    f = r["facts"]
    assert f["stories"]["value"] == 2 and f["stories"]["source"] == "CoStar" and "Vexcel" in f["stories"]["note"]
    assert f["stories_estimate"] == {**f["stories_estimate"], "value": 5, "source": "Vexcel"}
    assert f["parking_spaces"]["source"] == "CoStar" and f["parking_spaces"]["value"] == 96
    assert bf.fact_value(r, "rooftop_ac_units") == 4 and bf.fact_value(r, "footprint_sqft") == 12000
    assert bf.fact_value(r, "roof_condition") == 4 and "Good" in f["roof_condition"]["note"]
    assert bf.fact_value(r, "paved_area_sqft") == 30000
    assert f["building_height_ft"]["source"] == "Vexcel"  # CoStar has no height for this building
    assert r["sources"] == ["CoStar", "Vexcel"]
    # no CoStar record: the Vexcel estimates stand in, at low confidence
    v = bf.facts({"lat": 29.70, "lon": -95.30}, feature)["facts"]
    assert v["stories"]["source"] == "Vexcel" and v["stories"]["confidence"] == "low" and v["stories"]["value"] == 5
    assert v["parking_spaces"]["source"] == "Vexcel" and v["parking_spaces"]["value"] == 92
    assert v["ceiling_height_ft"]["value"] == 10.0  # 65 ft / 5 floors - 3 ft


def test_missing_data_is_omitted(index):
    assert bf.facts({"lat": 29.70, "lon": -95.30}, None) == {"facts": {}, "costar_id": None, "sources": []}
    assert bf.facts({}, None)["facts"] == {}  # no coordinates: no lookup, no crash
    bare = bf.facts({"lat": 29.78, "lon": -95.39}, _feature())
    assert bare["costar_id"] == "12" and bare["facts"] == {}
    assert bf.fact_value(bare, "year_built", "unknown") == "unknown"


def test_summary_carries_new_fields_additively(index):
    s = costar.summarize(costar.match(29.76, -95.37), 1500, 2200)
    assert s["year_built"] == 1998 and s["building_class"] == "B" and s["sprinklers"] is False and s["parking_spaces"] == 96
    assert s["matterport_models"] == ["Scan1"] and s["matterport_scans"] == [{"id": "Scan1", "caption": "Suite 105"}]
    assert s["listing_condition"] == "Good" and s["spaces"][0]["note_flags"] == ["restaurant", "second_generation"]


@pytest.mark.skipif(not (FIXTURES_DIR / "costar_index.json").exists(), reason="CoStar index not built (licensed kit)")
def test_real_index_record():
    costar._index.cache_clear()
    try:
        props, _ = costar._index()
        rec = next(p for p in props if p.get("year_built") and p.get("building_class") and p.get("parking_spaces"))
        r = bf.facts({"lat": rec["lat"], "lon": rec["lon"]}, None)
        match = costar.match(rec["lat"], rec["lon"])
        assert r["costar_id"] == str(match["id"])
        assert bf.fact_value(r, "year_built") == match["year_built"] and 1800 < match["year_built"] <= 2030
        assert all(f["value"] is not None for f in r["facts"].values())
        assert all(isinstance(m, str) for p in props[:200] for m in p["matterport_models"])  # unchanged shape
    finally:
        costar._index.cache_clear()
