"""Space program tests: what a request implies (size, occupancy, code needs, stated needs) and how a
building measures up. Deterministic, offline."""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

from config import business_types, metrics_registry, needs_registry, occupancy_codes  # noqa: E402
from services import program  # noqa: E402
from services.intent import parse_rules, target_sqft  # noqa: E402


def _code(p: dict, cid: str) -> dict:
    return next(c for c in p["code"] if c["id"] == cid)


def test_every_business_program_is_well_formed():
    codes, needs, reg = occupancy_codes(), needs_registry(), metrics_registry()
    for key, cfg in business_types().items():
        prog = cfg["program"]
        assert prog["occupancy"]["group"] in codes and prog.get("occupancy", {}).get("small_group", "B") in codes, key
        assert abs(sum(lf["share"] for lf in prog["occupancy"]["load_factors"]) - 1) < 1e-6, key
        assert prog["ground_floor"] in {"required", "preferred", "any"}
        assert "occupancy_requirements" in cfg["metrics"]
    assert reg["occupancy_requirements"]["owner"] == "compliance"
    assert all(n["owner"] in {"vexcel", "neighborhood", "compliance", "cost", "matterport"} for n in needs.values())


def test_restaurant_request_is_fully_acknowledged():
    i = parse_rules("60-seat restaurant with 10 staff in Houston Heights, must have parking, ideally a patio, open within 4 months")
    assert i.occupancy == {"seats": 60, "staff": 10} and i.location_text == "Houston Heights"
    assert {(n.id, n.priority) for n in i.needs} == {("parking", "must"), ("patio", "nice")}
    p = program.build(i)
    # full-service concept: (60 seats x 18 sq ft + 150 sq ft host/waiting) grossed up for 38% back of house
    assert p["size"]["concept"] == "full_service" and p["size"]["target_sqft"] == 1980 and target_sqft(i)[0] == 1980
    assert p["occupancy"]["group"] == "A-2" and p["occupancy"]["occupant_load"] >= 70  # 60 seats + 10 staff at least
    assert _code(p, "exits")["value"] == "2 exits"
    assert p["timeline"]["status"] == "tight"  # 4 months vs 4-8 month restaurant build-out
    labels = [a["label"] for a in p["acknowledged"]]
    assert "60 seats" in labels and "10 staff" in labels and any("A-2" in l for l in labels)


def test_small_assembly_is_group_b_and_large_needs_sprinklers():
    small = program.build(parse_rules("20-seat cafe in Houston"))
    assert small["occupancy"]["group"] == "B" and _code(small, "exits")["value"] == "1 exit"
    big = program.build(parse_rules("150 seat restaurant in Houston"))
    assert big["occupancy"]["group"] == "A-2" and _code(big, "sprinklers")["value"] == "Likely required"  # 5,250 sq ft and 100+ people


def test_business_specific_sizing_drivers():
    dental = parse_rules("dental office with 4 operatories in Houston, needs to be accessible")
    assert dental.business_type == "dental_clinic" and dental.occupancy == {"chairs": 4}
    assert program.target_size(dental)[0] == 400 + 4 * 400
    gym = parse_rules("boutique gym for classes of 20 people near Rice University")
    assert gym.business_type == "gym" and gym.occupancy == {"class_size": 20}
    office = parse_rules("office for a team of 12 in downtown Houston, near transit, want to buy")
    assert office.occupancy == {"employees": 12} and office.tenure == "buy" and office.location_text == "downtown Houston"


def test_stated_sqft_wins_but_conflict_is_noted():
    i = parse_rules("2,000 sq ft restaurant with 100 seats in Houston")
    target, _, _, basis = program.target_size(i)
    assert target == 2000 and any("suggests ~3,150" in b for b in basis)


def test_restroom_fixtures_follow_ipc_tiers():
    b = occupancy_codes()["B"]
    assert program._fixtures(20, b)["single_restroom_allowed"] is True
    fx = program._fixtures(120, b)  # 60 per sex: 2 for the first 50 + 1 for the next 10
    assert fx["water_closets_men"] == 3 and fx["water_closets"] == 6


def test_timeline_parsing():
    today = date(2026, 11, 14)
    assert program.parse_timeline("open within 3 months", today) == 3
    assert program.parse_timeline("in 6 weeks", today) == 2
    assert program.parse_timeline("open by March", today) == 4
    assert program.parse_timeline("asap", today) == 2
    assert program.parse_timeline("40 seats in Houston", today) is None


def test_site_checks_compare_building_to_program():
    p = program.build(parse_rules("60-seat restaurant in Houston, must have a drive-thru and parking"))
    one_story = {"building_type": "commercial", "footprint_sqft": 2600, "stories": 1, "roof_height_ft": 16, "paved_sqft": 9000}
    checks = {c["id"]: c for c in program.site_checks(p, one_story)}
    assert checks["size"]["status"] == checks["drive_thru"]["status"] == "pass"
    assert checks["ground_floor"]["status"] == "unknown"  # an aerial single-story estimate doesn't verify street level
    recorded = {c["id"]: c for c in program.site_checks(p, {**one_story, "stories_recorded": 1})}
    assert recorded["ground_floor"]["status"] == "pass" and "CoStar" in recorded["ground_floor"]["detail"]
    assert checks["ceiling"]["status"] == "pass" and checks["exits"]["status"] == "unknown"
    tight = {"building_type": "multiple_family", "footprint_sqft": 900, "stories": 4, "roof_height_ft": 44, "paved_sqft": 500}
    checks = {c["id"]: c for c in program.site_checks(p, tight)}
    assert checks["ground_floor"]["status"] == checks["drive_thru"]["status"] == checks["parking"]["status"] == "risk"
    assert checks["size"]["status"] == "risk"
    rows = program.compliance_rows(p, list(checks.values()))
    assert {r["id"] for r in rows} >= {"program_exits", "program_restrooms", "program_drive_thru"}


def test_bare_neighborhood_prefers_covered_city(monkeypatch):
    """'Montrose' alone matched Montrose County, Colorado; it must resolve to Montrose, Houston instead,
    while real cities outside coverage and explicit states are respected."""
    import asyncio

    from services import discovery, external

    places = {
        "montrose": {"name": "Montrose County", "display_name": "Montrose County, Colorado", "lat": 38.44, "lon": -108.24, "addresstype": "county"},
        "montrose, houston, tx": {"name": "Montrose", "display_name": "Montrose, Houston, Texas", "lat": 29.745, "lon": -95.39, "addresstype": "suburb"},
        "austin": {"name": "Austin", "display_name": "Austin, Texas", "lat": 30.27, "lon": -97.74, "addresstype": "city"},
        "montrose, co": {"name": "Montrose County", "display_name": "Montrose County, Colorado", "lat": 38.44, "lon": -108.24, "addresstype": "county"},
    }

    async def fake_geocode(text: str):
        return places.get(text.lower())

    monkeypatch.setattr(external, "geocode", fake_geocode)
    notes: list[str] = []
    assert asyncio.run(discovery.locate("Montrose", notes))["lat"] == 29.745 and "Montrose" in notes[0]
    assert asyncio.run(discovery.locate("Austin", []))["name"] == "Austin"
    assert asyncio.run(discovery.locate("Montrose, CO", []))["lat"] == 38.44
