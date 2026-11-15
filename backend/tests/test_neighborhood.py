"""Neighborhood agent signals: Census LODES workers/residents, direct competitors, walking reach and the
situational tool selection. Offline: tiny synthetic LODES files and a fake walking router."""
from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import pytest  # noqa: E402

from agents.base import EvidenceStore, RunContext, ToolBudget  # noqa: E402
from agents import neighborhood_agent as na  # noqa: E402
from config import business, settings  # noqa: E402
from services import lodes, rules, walking  # noqa: E402

LAT, LON = 29.7580, -95.3650


def _gz(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        fh.write(",".join(header) + "\n")
        for r in rows:
            fh.write(",".join(str(x) for x in r) + "\n")


@pytest.fixture
def lodes_tx(tmp_path, monkeypatch):
    """Three blocks: one at the property, one ~300 m away, one ~3 km away."""
    monkeypatch.setattr(settings, "lodes_dir", tmp_path)
    monkeypatch.setattr(settings, "lodes_year", 2023)
    lodes._indexes.clear()
    d = tmp_path / "tx"
    cns = [f"CNS{i:02d}" for i in range(1, 21)]
    wac_hdr = ["w_geocode", "C000", "CE01", "CE02", "CE03", *cns]
    def wac(block, total, office, food, retail):
        vals = {c: 0 for c in cns}
        vals["CNS12"], vals["CNS18"], vals["CNS07"] = office, food, retail
        return [block, total, total // 4, total // 4, total - 2 * (total // 4), *vals.values()]
    _gz(d / "tx_wac_S000_JT00_2023.csv.gz", wac_hdr, [wac("A", 1000, 600, 100, 50), wac("B", 500, 200, 80, 20), wac("C", 9999, 9000, 0, 0)])
    _gz(d / "tx_rac_S000_JT00_2023.csv.gz", ["h_geocode", "C000", "CE01", "CE02", "CE03"], [["A", 200, 20, 80, 100], ["B", 100, 50, 30, 20], ["C", 5000, 0, 0, 5000]])
    _gz(d / "tx_xwalk.csv.gz", ["tabblk2020", "blklatdd", "blklondd"], [["A", LAT, LON], ["B", LAT + 0.0027, LON], ["C", LAT + 0.027, LON]])
    yield
    lodes._indexes.clear()


def _ctx(business_type="restaurant", query="40-seat restaurant in Houston", places=None, extra=None) -> RunContext:
    _, jur = rules.jurisdiction_for("Houston", "Texas")
    places = places if places is not None else []
    return RunContext(
        query=query, intent={"business_type": business_type, "requirements": []},
        property={"id": "p", "lat": LAT, "lon": LON, "state": "Texas"}, feature=None,
        neighborhood={"places": places, "sources": [{"name": "OpenStreetMap places (Overpass)", "status": "used", "note": ""}], "fetched_radius_m": 1500, "user_radius_m": 500},
        neighbor_features=[], census={}, jurisdiction_key="houston-tx", jurisdiction=jur, target_sqft=1400, target_basis="test",
        extra_requirements=extra, evidence=EvidenceStore(), emit=lambda *a, **k: None,
    )


def _tools(ctx, signals=None):
    return {t.name: t for t in na.build_tools(ctx, ToolBudget(20), signals)}


def test_lodes_radius_counts_and_sectors(lodes_tx):
    w = lodes.workers_within("Texas", LAT, LON, 500)
    assert w["total_jobs"] == 1500 and w["by_sector"]["office"] == 800 and w["by_sector"]["food_service"] == 180
    assert lodes.workers_within("TX", LAT, LON, 100)["total_jobs"] == 1000  # only the block at the property
    r = lodes.residents_within("texas", LAT, LON, 500)
    assert r["employed_residents"] == 300 and r["earnings_mix_pct"]["high"] == 40
    with pytest.raises(ValueError):
        lodes.workers_within("Atlantis", LAT, LON, 500)


def test_daytime_workers_tool_with_benchmark(lodes_tx):
    out = json.loads(_tools(_ctx())["get_daytime_workers"].invoke({"radius_m": 500}))
    assert out["data"]["total_jobs"] == 1500 and "moderate for a restaurant" in out["summary"]  # weak is < 1,500
    out_small = json.loads(_tools(_ctx())["get_daytime_workers"].invoke({"radius_m": 100}))
    assert "strong" in out_small["summary"]  # benchmark scales with area: 1,000 jobs within 100 m is dense


def test_benchmark_bands_scale_with_radius():
    ctx = _ctx()
    assert na._benchmark(ctx, "daytime_workers", 9000, 500).startswith("strong")
    assert na._benchmark(ctx, "daytime_workers", 1000, 500).startswith("weak")
    assert na._benchmark(ctx, "daytime_workers", 3000, 500).startswith("moderate")
    assert na._benchmark(ctx, "daytime_workers", 3000, 1000).startswith("weak")  # 4x area -> 4x thresholds


def test_missing_data_is_unknown_not_zero():
    ctx = _ctx()
    ctx.property["state"] = "Atlantis"
    out = json.loads(_tools(ctx)["get_daytime_workers"].invoke({"radius_m": 500}))
    assert "unavailable" in out["summary"].lower() and "data" not in out


PLACES = [
    {"id": "1", "name": "Taqueria A", "category": "amenity=restaurant", "group": "food_drink", "lat": LAT, "lon": LON + 0.001, "distance_m": 100, "cuisine": "mexican", "brand": None},
    {"id": "2", "name": "Chipotle", "category": "amenity=fast_food", "group": "food_drink", "lat": LAT, "lon": LON + 0.002, "distance_m": 200, "cuisine": "mexican;tex-mex", "brand": "Chipotle"},
    {"id": "3", "name": "Sushi B", "category": "amenity=restaurant", "group": "food_drink", "lat": LAT, "lon": LON + 0.003, "distance_m": 300, "cuisine": "sushi", "brand": None},
    {"id": "4", "name": "Bar C", "category": "amenity=bar", "group": "food_drink", "lat": LAT, "lon": LON + 0.0035, "distance_m": 350, "cuisine": None, "brand": None},
    {"id": "5", "name": "Stop 1", "category": "highway=bus_stop", "group": "transit", "lat": LAT + 0.002, "lon": LON, "distance_m": 220, "cuisine": None, "brand": None},
    {"id": "6", "name": "Dr Smile", "category": "amenity=dentist", "group": "dental_medical", "lat": LAT, "lon": LON - 0.004, "distance_m": 400, "cuisine": None, "brand": None},
]


def test_direct_and_same_kind_competitors():
    ctx = _ctx(query="Mexican restaurant with 40 seats in Houston", places=PLACES)
    out = json.loads(_tools(ctx)["find_direct_competitors"].invoke({"radius_m": 500}))
    d = out["data"]
    assert d["direct_competitors"] == 3  # bar is not a restaurant competitor; dentist obviously not
    assert d["kind"] == "mexican" and d["same_kind_competitors"] == 2 and d["chains"] == 1
    dental = json.loads(_tools(_ctx("dental_clinic", places=PLACES))["find_direct_competitors"].invoke({"radius_m": 500}))
    assert dental["data"]["direct_competitors"] == 1


def test_walkable_reach_counts_barriers(monkeypatch):
    # Pretend the sushi place and the bar are across a highway: long walks.
    def fake(origin, dests):
        return [60 * (1 if d[1] < LON + 0.0025 else 30) for d in dests], True
    monkeypatch.setattr(walking, "walk_seconds", fake)
    out = json.loads(_tools(_ctx(places=PLACES))["get_walkable_reach"].invoke({"minutes": 10}))
    d = out["data"]
    assert d["places_in_circle"] == 5 and d["walkable_places"] == 3 and d["blocked_pct"] == 40 and d["routed"] is True


def test_signals_are_situational():
    office = _ctx("office", query="office for 12 people in Houston")
    assert set(_tools(office)) >= {"get_walkable_reach"} and "find_direct_competitors" not in _tools(office)
    assert "get_daytime_workers" not in _tools(office)  # not configured for offices...
    busy = _ctx("office", query="office in Houston with lots of foot traffic")
    names, why = na.select_signals(busy)
    assert "daytime_workers" in names and "foot traffic" in why["daytime_workers"]  # ...unless the user asks
    dental = na.select_signals(_ctx("dental_clinic"))[0]
    assert dental == ["residents", "competitors"]
    # Census demographics tool is only offered when a key exists (otherwise it can only say "unavailable").
    assert ("get_demographics" in _tools(_ctx())) == bool(settings.census_api_key)


def test_extra_requirements_drive_kind_and_signals():
    ctx = _ctx(query="restaurant in Houston", extra="we serve Thai food and want a walkable area")
    assert na.detect_kind(ctx)[0] == "thai"
    assert "walk_access" in na.select_signals(ctx)[0]


def test_config_signals_reference_known_tools():
    for key in ("restaurant", "dental_clinic", "gym", "office", "retail"):
        sig = business(key)["neighborhood"]["signals"]
        assert set(sig) <= {"daytime_workers", "residents", "competitors", "walk_access"}, key
