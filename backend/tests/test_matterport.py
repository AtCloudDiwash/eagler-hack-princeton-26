"""Matterport integration tests, fully offline: URL parsing, scan normalization (old recordings and the current
tiered live shape), interior facts, scan identity, agent tools and run(), availability, the link/unlink
endpoints and the live client against a mocked GraphQL endpoint (error codes, retry, tier independence).
RAW is a synthetic scan in the older recorded shape; LIVE_CORE / LIVE_PI are trimmed copies of real Model API
responses (omitted nulls, metre openings) for an industrial building."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import httpx  # noqa: E402
import pytest  # noqa: E402

import db  # noqa: E402
from agents import matterport_agent  # noqa: E402
from agents.base import EvidenceStore, RunContext, ToolBudget  # noqa: E402
from config import settings  # noqa: E402
from services import matterport, scan_identity  # noqa: E402

MODEL_ID = "TestScan123"  # 11 characters, like real Matterport ids

RAW = {
    "model_id": MODEL_ID,
    "core": {
        "id": MODEL_ID, "name": "Former diner, ground floor", "created": "2026-03-02T10:00:00Z",
        "floors": [{"id": "f1", "label": "", "sequence": 0}],
        "rooms": [
            {"id": "r1", "label": "Dining", "tags": [], "keywords": ["dining"], "classifications": [{"label": "Dining Room", "confidence": 0.93}], "floor": {"id": "f1"}},
            {"id": "r2", "label": None, "tags": [], "keywords": [], "classifications": [{"label": "Kitchen", "confidence": 0.88}], "floor": {"id": "f1"}},
            {"id": "r3", "label": "Restroom A", "tags": [], "keywords": [], "classifications": [{"label": "Bathroom", "confidence": 0.9}], "floor": {"id": "f1"}},
            {"id": "r4", "label": "Restroom B", "tags": [], "keywords": [], "classifications": [{"label": "Bathroom", "confidence": 0.9}], "floor": {"id": "f1"}},
        ],
        "mattertags": [{"label": "Hood (10 ft)", "description": "Existing Type I hood over the cook line"}],
    },
    "insights": {
        "dimensionEstimates": {"area": 1650.0, "areaIndoor": 1580.0, "units": "imperial"},
        "floors": [{"id": "f1", "dimensionEstimates": {"area": 1650.0, "areaIndoor": 1580.0}}],
        "rooms": [
            {"id": "r1", "dimensionEstimates": {"areaIndoor": 980.0, "height": 11.5, "width": 35.0, "depth": 28.0}},
            {"id": "r2", "dimensionEstimates": {"areaIndoor": 420.0, "height": 9.5, "width": 21.0, "depth": 20.0}},
            {"id": "r3", "dimensionEstimates": {"areaIndoor": 60.0, "height": 8.0}},
            {"id": "r4", "dimensionEstimates": {"areaIndoor": 0, "height": None}},
        ],
        "objectAnnotations": [{"label": None, "confidence": 0.81, "classification": {"label": "Sink"}, "room": {"id": "r2"}}],
    },
    "insights_note": None,
}


def _ctx(prop_extra: dict | None = None) -> RunContext:
    return RunContext(
        query="40-seat restaurant in Houston", intent={"business_type": "restaurant", "requirements": []},
        property={"id": "p", "lat": 29.8, "lon": -95.4, **(prop_extra or {})}, feature=None, neighborhood={}, neighbor_features=[], census={},
        jurisdiction_key="houston-tx", jurisdiction={"name": "Houston, TX"}, target_sqft=1400, target_basis="test", extra_requirements=None,
        evidence=EvidenceStore(), emit=lambda *a, **k: None,
    )


@pytest.fixture
def fixture_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(matterport, "FIXTURE_DIR", tmp_path)
    monkeypatch.setattr(settings, "matterport_api_key", None)
    monkeypatch.setattr(settings, "matterport_api_secret", None)
    return tmp_path


def test_parse_model_id_accepts_urls_and_ids():
    assert matterport.parse_model_id("https://my.matterport.com/show/?m=SxQL3iGyoDo&play=1") == "SxQL3iGyoDo"
    assert matterport.parse_model_id("my.matterport.com/show/?m=SxQL3iGyoDo") == "SxQL3iGyoDo"
    assert matterport.parse_model_id("https://my.matterport.com/models/SxQL3iGyoDo") == "SxQL3iGyoDo"
    assert matterport.parse_model_id("  SxQL3iGyoDo ") == "SxQL3iGyoDo"
    assert matterport.parse_model_id("https://example.com/tour") is None
    assert matterport.parse_model_id("") is None


def test_summarize_merges_dimensions_and_classifications():
    s = matterport.summarize(RAW)
    assert s["total_indoor_area_sqft"] == 1580.0 and s["insights_available"]
    kitchen = next(r for r in s["rooms"] if r["id"] == "r2")
    assert kitchen["label"] == "Kitchen" and kitchen["height_ft"] == 9.5  # unlabeled room named by its classification
    assert next(r for r in s["rooms"] if r["id"] == "r4")["area_sqft"] is None  # zero/None dimensions -> unknown
    assert s["floors"][0]["label"] == "Floor 1"
    assert s["objects"] == [{"label": "Sink", "confidence": 0.81, "room": "Kitchen"}]


def test_summarize_without_insights_keeps_rooms():
    s = matterport.summarize({**RAW, "insights": None, "insights_note": "not enabled"})
    assert len(s["rooms"]) == 4 and s["total_indoor_area_sqft"] is None and not s["insights_available"]
    assert all(r["area_sqft"] is None for r in s["rooms"])


def test_search_covers_rooms_objects_and_tags():
    s = matterport.summarize(RAW)
    assert matterport.search(s, "hood")["tags"][0]["label"] == "Hood (10 ft)"
    assert matterport.search(s, "sink")["objects"][0]["room"] == "Kitchen"
    assert matterport.search(s, "restroom")["rooms"] == ["Restroom A", "Restroom B"]


def test_availability(fixture_dir):
    assert matterport_agent.available(_ctx())[0] is False
    ok, reason = matterport_agent.available(_ctx({"matterport_model_id": MODEL_ID}))
    assert ok is False and "MATTERPORT_API_KEY" in reason  # tour linked, but no data source
    (fixture_dir / f"{MODEL_ID}.json").write_text(json.dumps(RAW))
    assert matterport_agent.available(_ctx({"matterport_model_id": MODEL_ID})) == (True, "")
    assert matterport.link_info({"matterport_model_id": MODEL_ID})["data"] == "recorded"


def test_agent_tools_register_evidence():
    ctx = _ctx({"matterport_model_id": MODEL_ID})
    tools = {t.name: t for t in matterport_agent.build_tools(ctx, ToolBudget(6), matterport.summarize(RAW))}
    out = json.loads(tools["count_rooms_of_type"].invoke({"room_type": "restroom"}))
    assert out["evidence_id"] == "E1" and out["data"]["count"] == 2
    heights = json.loads(tools["check_ceiling_heights"].invoke({"min_clear_ft": 10}))
    assert heights["data"]["min_ft"] == 8.0 and len(heights["data"]["rooms_below_threshold"]) == 2
    fit = json.loads(tools["compare_area_to_need"].invoke({}))
    assert fit["data"]["ratio"] == round(1580 / 1400, 2)
    assert ctx.evidence.get("E1").source.startswith("Matterport")


def test_skipped_report_marks_interior_metrics_unknown(fixture_dir):
    rep = asyncio.run(matterport_agent.run(_ctx()))
    assert rep.status == "skipped"
    assert {a.metric_id for a in rep.metric_assessments} == {"kitchen_infrastructure", "interior_layout"}
    assert all(a.status == "unknown" for a in rep.metric_assessments)


def test_fetch_model_live_with_partial_insights(fixture_dir, monkeypatch):
    """Core query succeeds; the Property Intelligence query is denied -> rooms kept, note recorded."""
    monkeypatch.setattr(settings, "matterport_api_key", "id")
    monkeypatch.setattr(settings, "matterport_api_secret", "secret")
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append((body["query"].split("(")[0].strip(), req.headers["authorization"]))
        if "TurnkeyModelCore" in body["query"]:
            return httpx.Response(200, json={"data": {"model": RAW["core"]}})
        return httpx.Response(200, json={"data": {"model": None}, "errors": [{"message": "Not authorized for dimensionEstimates"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(matterport.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    raw = asyncio.run(matterport.fetch_model("LiveScan123", use_cache=False))
    assert raw["core"]["name"] == RAW["core"]["name"] and raw["insights"] is None
    assert "Not authorized" in raw["insights_note"]
    assert len(seen) == 2 and seen[0][1].startswith("Basic ")


def test_link_and_unlink_endpoints(fixture_dir):
    from fastapi.testclient import TestClient

    import main

    db.save_property({"id": "mp-test", "lat": 29.76, "lon": -95.37, "address": "1 Test St"}, None)
    with TestClient(main.app) as client:
        assert client.put("/api/properties/mp-test/matterport", json={"tour": "https://example.com"}).status_code == 400
        r = client.put("/api/properties/mp-test/matterport", json={"tour": f"https://my.matterport.com/show/?m={MODEL_ID}"})
        assert r.status_code == 200
        mp = r.json()["matterport"]
        assert mp["model_id"] == MODEL_ID and mp["data"] == "embed_only" and MODEL_ID in mp["embed_url"]
        # a re-run search re-saves the candidate without the link: it must survive
        db.save_property({"id": "mp-test", "lat": 29.76, "lon": -95.37, "address": "1 Test St"}, None)
        assert client.get("/api/properties/mp-test").json()["matterport"]["model_id"] == MODEL_ID
        assert client.delete("/api/properties/mp-test/matterport").json()["matterport"] is None


# ---------------------------------------------------------------- current live shape (trimmed real responses)

LIVE_ID = "LiveShape01"
LIVE_CORE = {
    "id": LIVE_ID, "name": "Northwest Trade Center - 9750 Tanner Rd ", "state": "active", "accessVisibility": "unlisted",
    "created": "2026-11-10T00:12:47Z", "modified": "2026-11-12T03:47:49Z",
    "address": {"address": "9750 Tanner Rd, Houston, TX, 77041, US", "locality": "Houston", "administrativeArea": "TX", "postalCode": "77041", "status": "parsed"},
    "geolocation": {"lat": "29.8502572", "long": "-95.5340642"},
    "publication": {"published": True, "url": "https://my.matterport.com/show/?m=x", "presentedBy": "LoopNet"},
    "propertyClassifications": [{"classification": "factory_industrial", "type": "vision"}],
    "floors": [{"id": "f1", "label": "Floor 1", "sequence": 0}],
    "rooms": [
        {"id": "wh", "label": "Warehouse", "tags": ["other"], "keywords": ["indoor"], "floor": {"id": "f1"}},
        {"id": "void", "label": "", "tags": [], "keywords": ["hide", "nonArea", "indoor"], "floor": {"id": "f1"}},
        {"id": "bath", "label": "", "tags": [], "keywords": ["indoor"], "floor": {"id": "f1"}},
        {"id": "hall", "label": "", "tags": ["hallway"], "keywords": ["indoor"], "floor": {"id": "f1"}},
        {"id": "break", "label": "Breakroom", "tags": [], "keywords": ["indoor"], "floor": {"id": "f1"}},
        {"id": "conf", "label": "Conference Room", "tags": [], "keywords": ["indoor"], "floor": {"id": "f1"}},
        {"id": "gard", "label": "", "tags": [], "keywords": ["indoor"], "floor": {"id": "f1"}},
        {"id": "off", "label": "", "tags": ["other"], "keywords": ["indoor"], "floor": {"id": "f1"}},
    ],
    "labels": [], "notes": [], "mattertagsWithType": [], "measurementPaths": [],
}


def _pi_room(rid, cls, area, height=None, openings=(), keywords=("indoor",)):
    return {
        "id": rid, "classifications": [{"label": cls, "confidence": 1.0, "defaultKeywords": list(keywords)}],
        "ceiling": {"minHeight": height, "maxHeight": height} if height else {},  # nulls are omitted: {} when unknown
        "dimensionEstimates": {"area": area, "areaIndoor": area, "areaIndoorWithWalls": area * 1.05, "height": height or 0.0, "width": 0.0, "depth": 0.0, "units": "imperial"},
        "boundary": {"edges": [{"type": "wall", "openings": []}, {"type": "wall", "openings": list(openings)}]},
    }


DOCK = {"type": "doorway", "label": "door-unknown", "width": 4.0658078567415625, "height": 2.032}  # metres: 160 x 80 in
WH_HALL = {"type": "doorway", "label": "door-pivot", "width": 0.9002451120238895, "height": 2.7003872394561768}  # 35 in
BATH_HALL = {"type": "doorway", "label": "door-unknown", "width": 0.9144, "height": 2.032}  # exactly 36 x 80 in
NARROW = {"type": "doorway", "label": "door-pivot", "width": 0.762, "height": 2.032}  # 30 in
LIVE_PI = {
    "dimensionEstimates": {"area": 8100.0, "areaIndoor": 8100.0, "areaIndoorWithWalls": 8400.0, "units": "imperial"},
    "floors": [{"id": "f1", "dimensionEstimates": {"area": 8100.0, "areaIndoor": 8100.0, "areaIndoorWithWalls": 8400.0, "units": "imperial"}}],
    "rooms": [
        _pi_room("wh", "Other", 6383.4, None, [DOCK, WH_HALL]),
        _pi_room("void", "Void", 14.4, None, keywords=("nonArea", "hide")),
        _pi_room("bath", "Bathroom", 139.2, 9.04, [BATH_HALL]),
        _pi_room("hall", "Hallway", 100.1, 9.01, [WH_HALL, BATH_HALL]),
        _pi_room("break", "Balcony", 288.5, 9.04, [{"type": "window", "label": "window-unknown", "width": 3.013776268094896, "height": 2.76}]),
        _pi_room("conf", "Hallway", 132.8, 9.07),
        _pi_room("gard", "Garden", 50.0, 9.42),
        _pi_room("off", "Office", 214.2, 8.99, [{"type": "window", "label": "window-unknown", "width": 0.9340146162428878, "height": 2.813}, NARROW,
                                                 {"type": "divider", "label": None, "width": 2.0, "height": 2.4}]),
    ],
}
LIVE_RAW = {"model_id": LIVE_ID, "schema": 2, "core": LIVE_CORE, "insights": LIVE_PI, "insights_note": None, "tiers": {"core": True, "pi": True}}
# CoStar's record for this building is ~89 m from the scan's geolocation
PROP = {"id": "p-nwtc", "lat": 29.850575, "lon": -95.533213, "address": "9700 Tanner Rd, Houston, TX", "building_name": "Northwest Trade Center", "costar_id": 23296}
FACT_KEYS = {"indoor_area_sqft", "indoor_area_with_walls_sqft", "ceiling", "rooms_by_type", "doorways", "narrowest_door_in", "wide_doors",
             "windows", "owner_annotations", "tiers_available", "objects_available", "notes"}


def _room(s, label):
    return next(r for r in s["rooms"] if r["label"] == label)


def test_live_shape_drops_void_and_user_label_wins():
    s = matterport.summarize(LIVE_RAW)
    assert len(s["rooms"]) == 7 and s["hidden_room_count"] == 1
    assert all(r["id"] != "void" for r in s["rooms"])
    br = _room(s, "Breakroom")  # classifier said Balcony
    assert br["label_source"] == "user" and br["type"] == "Balcony" and br["category"] == "kitchen"
    assert _room(s, "Conference Room")["category"] == "office"  # classifier said Hallway
    assert _room(s, "Bathroom")["label_source"] == "classifier" and _room(s, "Bathroom")["category"] == "restroom"
    assert s["name"] == "Northwest Trade Center - 9750 Tanner Rd" and s["total_indoor_area_with_walls_sqft"] == 8400.0
    assert s["tiers_available"] == ["core", "pi", "boundary"]
    assert s["identity"]["lat"] == 29.8502572 and s["identity"]["classifications"] == ["factory_industrial"]


def test_whole_word_room_types():
    s = matterport.summarize(LIVE_RAW)
    hall, garden = _room(s, "Hallway"), _room(s, "Garden")
    assert hall["category"] == "circulation" and not matterport.room_matches(hall, matterport.ROOM_TYPES["open_area"])
    assert garden["category"] == "exterior" and not matterport.room_matches(garden, matterport.ROOM_TYPES["office"])
    assert _room(s, "Warehouse")["category"] == "open_area"

    def cat(label, rtype=None):
        r = {"label": label, "label_source": "user", "type": rtype, "keywords": []}
        return matterport.room_category(r)

    assert cat("Open Office") == "open_area" and cat("Private Office") == "office"
    assert cat("Restrooms") == "restroom" and cat("Mens WC") == "restroom" and cat("Wcfoo") is None
    assert cat("Suite A", "Kitchen") == "kitchen"  # a name that says nothing about use falls back to the classifier
    assert cat("Hallway", "Office") == "circulation"  # ... but a descriptive name wins
    assert matterport.search(s, "toilet")["rooms"] == ["Bathroom"]


def test_interior_facts_contract_and_openings_in_inches():
    f = matterport.interior_facts(matterport.summarize(LIVE_RAW))
    assert set(f) == FACT_KEYS
    assert set(f["ceiling"]) == {"min_ft", "max_ft", "median_ft", "measured_area_share", "unmeasured_rooms"}
    assert set(f["rooms_by_type"]) == {"restroom", "kitchen", "office", "storage", "open_area"}
    assert f["rooms_by_type"] == {"restroom": 1, "kitchen": 1, "office": 2, "storage": 0, "open_area": 1}
    # metres -> inches; a door shared by two rooms counted once; dividers ignored
    widths = sorted(d["width_in"] for d in f["doorways"])
    assert widths == [30, 35, 36, 160]
    assert next(d for d in f["doorways"] if d["width_in"] == 36) == {"room": "Bathroom / Hallway", "width_in": 36, "height_in": 80, "kind": "door (type unknown)"}
    assert f["narrowest_door_in"] == 30 and f["wide_doors"] == 1
    assert f["windows"] == {"count": 2, "total_width_ft": round((119 + 37) / 12, 1), "rooms": ["Breakroom", "Office"]}
    assert f["indoor_area_sqft"] == 8100.0 and f["indoor_area_with_walls_sqft"] == 8400.0
    assert f["tiers_available"] == ["core", "pi", "boundary"] and f["objects_available"] is False and f["owner_annotations"] == 0


def test_ceiling_coverage_reports_unmeasured_area():
    f = matterport.interior_facts(matterport.summarize(LIVE_RAW))
    c = f["ceiling"]
    room_area = 6383.4 + 139.2 + 100.1 + 288.5 + 132.8 + 50.0 + 214.2
    assert c["min_ft"] == 9.0 and c["max_ft"] == 9.4
    assert c["measured_area_share"] == round((room_area - 6383.4) / room_area, 2)
    assert c["unmeasured_rooms"] == [{"label": "Warehouse", "area_sqft": 6383.4}]
    assert any("Warehouse" in n for n in f["notes"])


def test_old_recording_facts_degrade_gracefully():
    f = matterport.interior_facts(matterport.summarize({**RAW, "insights": None}))
    assert set(f) == FACT_KEYS and f["tiers_available"] == ["core"]
    assert f["indoor_area_sqft"] is None and f["ceiling"]["min_ft"] is None and f["ceiling"]["measured_area_share"] is None
    assert f["doorways"] == [] and f["wide_doors"] is None and f["windows"]["count"] is None
    assert f["owner_annotations"] == 1  # the Mattertag (old `mattertags` key)


def test_live_shape_agent_tools(monkeypatch):
    ctx = _ctx({"matterport_model_id": LIVE_ID})
    ctx.program = {"building": {"min_ceiling_ft": 12}, "needs": []}
    s = matterport.summarize(LIVE_RAW)
    tools = {t.name: t for t in matterport_agent.build_tools(ctx, ToolBudget(10), s, matterport.interior_facts(s), scan_identity.assess(LIVE_ID, s["identity"], PROP))}
    assert {"get_scan_identity", "check_doorways", "check_windows", "check_ceiling_heights", "compare_area_to_need"} <= set(tools)
    assert "hood" not in tools["search_scan"].description.lower() or "no object detection" in tools["search_scan"].description
    ident = json.loads(tools["get_scan_identity"].invoke({}))
    assert ident["data"]["verdict"] == "verified"
    ceil = json.loads(tools["check_ceiling_heights"].invoke({}))
    assert ceil["data"]["threshold_ft"] == 12 and "Warehouse" in ceil["summary"] and len(ceil["data"]["rooms_below_threshold"]) == 6
    doors = json.loads(tools["check_doorways"].invoke({}))
    assert doors["data"]["narrowest_door_in"] == 30 and len(doors["data"]["below_32_in"]) == 1 and len(doors["data"]["wide_doors"]) == 1
    fit = json.loads(tools["compare_area_to_need"].invoke({}))
    assert fit["data"]["measured_indoor_sqft"] == 8400.0  # area with walls preferred


def test_tools_follow_available_tiers():
    ctx = _ctx({"matterport_model_id": MODEL_ID})
    s = matterport.summarize({**RAW, "insights": None})
    names = {t.name for t in matterport_agent.build_tools(ctx, ToolBudget(6), s)}
    assert names == {"get_scan_identity", "get_scan_overview", "list_rooms", "count_rooms_of_type", "search_scan"}


def test_skipped_report_lists_matterport_needs(fixture_dir):
    ctx = _ctx()
    ctx.program = {"needs": [
        {"id": "grease_trap", "label": "Grease interceptor", "priority": "must", "owner": "matterport", "check": None, "triggers": "grease"},
        {"id": "parking", "label": "Parking", "priority": "nice", "owner": "compliance", "check": None, "triggers": "parking"},
    ]}
    rep = asyncio.run(matterport_agent.run(ctx))
    assert rep.status == "skipped" and "Grease interceptor" in rep.missing_information and "Parking" not in rep.missing_information


# ---------------------------------------------------------------- scan identity

def test_assess_verdicts():
    s = matterport.summarize(LIVE_RAW)
    ok = scan_identity.assess(LIVE_ID, s["identity"], PROP)
    assert ok["verdict"] == "verified" and 50 < ok["distance_m"] < 150 and set(ok) >= {"verdict", "reason", "model_id", "name", "address", "distance_m", "alternatives_checked", "captured", "age_years", "floor_match"}
    far = scan_identity.assess(LIVE_ID, s["identity"], {**PROP, "lat": 29.76, "lon": -95.37})
    assert far["verdict"] == "mismatch" and far["distance_m"] > 10_000
    gym = scan_identity.assess("NLpW1UAp1HJ", {"name": "Fitness Center", "lat": 29.85058, "lon": -95.53322, "classifications": ["fitness_sports"]}, PROP)
    assert gym["verdict"] == "amenity" and "fitness" in gym["reason"]
    near = scan_identity.assess("x", {"name": "Unit tour", "lat": 29.85058, "lon": -95.53322}, PROP)
    assert near["verdict"] == "likely"
    suite = scan_identity.assess("x", {"name": "Suite 855", "lat": 29.85058, "lon": -95.53322}, {**PROP, "best_space": {"suite": "855"}})
    assert suite["verdict"] == "verified" and "855" in suite["reason"]
    other = scan_identity.assess("x", {"name": "Suite 230", "lat": 29.85058, "lon": -95.53322}, {**PROP, "best_space": {"suite": "855"}})
    assert other["verdict"] == "likely" and "230" in other["reason"]
    assert scan_identity.assess("x", {"name": None, "address": None, "lat": None}, PROP)["verdict"] == "unknown"


def test_assess_downgrades_old_other_floor_and_whole_building_scans():
    here = {"lat": 29.85058, "lon": -95.53322}
    suite_prop = {**PROP, "best_space": {"suite": "855", "floor": "8th Floor"}}
    fresh = scan_identity.assess("x", {"name": "Suite 855", **here, "captured": str(date.today())[:10]}, suite_prop)
    assert fresh["verdict"] == "verified" and fresh["floor_match"] is True
    old = scan_identity.assess("x", {"name": "Suite 855", **here, "captured": "2017-03-01"}, suite_prop)
    assert old["verdict"] == "likely" and "years ago" in old["reason"] and old["age_years"] > 3
    # a scan of the building (street address matches) that shows another floor than the listed suite
    other_floor = scan_identity.assess("x", {"name": "Floor 12 tour", "address": PROP["address"], **here}, suite_prop)
    assert other_floor["verdict"] == "likely" and other_floor["floor_match"] is False and "floor 12" in other_floor["reason"]
    whole = scan_identity.assess("x", {"name": "Building tour", "address": PROP["address"], **here, "floor_count": 4}, suite_prop)
    assert whole["verdict"] == "likely" and "whole-building" in whole["reason"]
    # Suite 1080 vs a ground-floor Suite 170: the floor difference is spelled out
    tower = scan_identity.assess("x", {"name": "1301 Fannin, Suite 1080", **here}, {**PROP, "best_space": {"suite": "170", "floor": "First Floor"}})
    assert tower["verdict"] == "likely" and "floor 10" in tower["reason"] and tower["floor_match"] is False


def test_safety_net_recording_is_served_only_when_live_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(matterport, "FALLBACK_DIR", tmp_path)
    (tmp_path / f"{LIVE_ID}.json").write_text(json.dumps({**LIVE_RAW, "recorded_at": "2026-11-15"}))
    monkeypatch.setattr(settings, "matterport_api_key", "id")
    monkeypatch.setattr(settings, "matterport_api_secret", "secret")
    assert matterport.data_mode(LIVE_ID) == "live"  # the UI label doesn't change because a safety net exists

    async def down(model_id):
        raise httpx.ConnectError("network unreachable")

    monkeypatch.setattr(matterport, "_fetch_live", down)
    raw = asyncio.run(matterport.fetch_model(LIVE_ID, use_cache=False))
    assert raw["served_from"] == "fallback" and "safety-net copy recorded 2026-11-15" in raw["insights_note"]
    with pytest.raises(httpx.ConnectError):
        asyncio.run(matterport.fetch_model("NoRecording", use_cache=False))


def test_default_scan_prefers_non_amenity_caption():
    assert scan_identity.default_scan(None) is None
    assert scan_identity.default_scan({"matterport_models": ["AAAAAAAAAAA", "BBBBBBBBBBB"]}) == "AAAAAAAAAAA"
    rec = {"matterport_models": ["AAAAAAAAAAA", "BBBBBBBBBBB"], "matterport_scans": [{"id": "AAAAAAAAAAA", "caption": "Fitness Center"}, {"id": "BBBBBBBBBBB", "caption": "Suite 855"}]}
    assert scan_identity.default_scan(rec) == "BBBBBBBBBBB"
    rec["matterport_scans"][1]["caption"] = "Lobby"
    assert scan_identity.default_scan(rec) is None  # only amenity tours: link nothing rather than a lobby


@pytest.fixture
def mock_api(fixture_dir, monkeypatch):
    """Live mode against a mocked GraphQL endpoint, with caching off. Returns (models by id, list of seen queries)."""
    monkeypatch.setattr(settings, "matterport_api_key", "id")
    monkeypatch.setattr(settings, "matterport_api_secret", "secret")
    monkeypatch.setattr(matterport, "RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(db, "cache_get", lambda *a, **k: None)
    models: dict[str, dict] = {}
    seen: list[str] = []
    not_found = {"message": "Error fetching data (code: not.found): Not Found", "extensions": {"code": "not.found", "retry": "false", "httpCode": 404}}

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        q, var = body["query"], body.get("variables") or {}
        name = q.split("{")[0].split("(")[0].replace("query", "").strip()
        seen.append(name)
        if name == "TurnkeyModelCore":
            m = models.get(var["id"])
            return httpx.Response(200, json={"data": {"model": m["core"]}} if m else {"data": {"model": None}, "errors": [not_found]})
        if name == "TurnkeyModelInsights":
            m = models.get(var["id"])
            return httpx.Response(200, json={"data": {"model": m.get("pi")}} if m and m.get("pi") else {"data": {"model": None}, "errors": [not_found]})
        if name == "TurnkeyScanIdentities":
            import re as _re
            data = {alias: (models.get(mid) or {}).get("core") for alias, mid in _re.findall(r'(m\d+): model\(id: "(\w+)"\)', q)}
            return httpx.Response(200, json={"data": data})
        if name == "TurnkeyScanSearch":
            return httpx.Response(200, json={"data": {"models": {"results": []}}})
        return httpx.Response(400, json={})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return models, seen


def _core(mid, name, lat, lon, classes=()):
    return {"id": mid, "name": name, "address": {"address": "9750 Tanner Rd, Houston, TX"}, "geolocation": {"lat": str(lat), "long": str(lon)},
            "propertyClassifications": [{"classification": c, "type": "vision"} for c in classes], "floors": [{"id": "f1", "sequence": 0}],
            "rooms": [{"id": "r1", "label": "Suite", "floor": {"id": "f1"}}]}


def test_choose_scan_replaces_amenity_with_costar_alternative(mock_api):
    models, seen = mock_api
    models["GymScan0001"] = {"core": _core("GymScan0001", "Fitness Center", 29.85058, -95.53322, ["fitness_sports"])}
    models["SuiteScan01"] = {"core": _core("SuiteScan01", "Northwest Trade Center Suite 100", 29.85060, -95.53320)}
    models["FarScan0001"] = {"core": _core("FarScan0001", "Somewhere else", 29.70, -95.30)}
    prop = {**PROP, "id": "p-choose", "matterport_model_id": "GymScan0001"}
    out = asyncio.run(scan_identity.choose_scan(prop, ["GymScan0001", "FarScan0001", {"id": "SuiteScan01", "caption": None}, "MissingScan"], use_cache=False))
    assert out["switched"] and out["model_id"] == "SuiteScan01" and out["verdict"] == "verified"
    assert out["linked_model_id"] == "GymScan0001" and out["linked_verdict"] == "amenity" and out["alternatives_checked"] == 3
    assert "TurnkeyScanIdentities" in seen
    # a user-chosen link is not replaced; the better scan is only suggested
    kept = asyncio.run(scan_identity.choose_scan(prop, ["SuiteScan01"], allow_switch=False, use_cache=False))
    assert not kept["switched"] and kept["model_id"] == "GymScan0001" and kept["verdict"] == "amenity" and kept["alternative"]["model_id"] == "SuiteScan01"


def test_choose_scan_keeps_matching_scan_without_extra_calls(mock_api):
    models, seen = mock_api
    models[LIVE_ID] = {"core": LIVE_CORE, "pi": LIVE_PI}
    out = asyncio.run(scan_identity.choose_scan({**PROP, "matterport_model_id": LIVE_ID}, ["SuiteScan01"], use_cache=False))
    assert out["verdict"] == "verified" and not out["switched"] and out["alternatives_checked"] == 0
    assert "TurnkeyScanIdentities" not in seen and "TurnkeyScanSearch" not in seen


def _fake_run_agent(calls):
    async def fake(ctx, agent, role, task, tools, budget, metric_ids=None):
        calls.append({"role": role, "task": task, "tools": [t.name for t in tools]})
        return matterport_agent.deterministic_report(ctx, agent, "Interior checked.", [], [], [], status="completed")
    return fake


def test_run_registers_scan_facts_and_shares_them(mock_api, monkeypatch):
    models, _ = mock_api
    models[LIVE_ID] = {"core": LIVE_CORE, "pi": LIVE_PI}
    calls: list = []
    monkeypatch.setattr(matterport_agent, "run_agent", _fake_run_agent(calls))
    ctx = _ctx({**PROP, "matterport_model_id": LIVE_ID})
    rep = asyncio.run(matterport_agent.run(ctx))
    assert rep.status == "completed" and rep.summary == "Interior checked."
    eid = ctx.shared["interior_facts_eid"]
    ev = ctx.evidence.get(eid)
    assert ev.tool == "scan_facts" and ev.agent == "matterport" and set(ev.data) == FACT_KEYS | {"identity"}
    assert ctx.shared["interior_facts"]["narrowest_door_in"] == 30 and ctx.shared["scan_identity"]["verdict"] == "verified"
    assert calls[0]["tools"][0] == "get_scan_identity" and "check_doorways" in calls[0]["tools"] and eid in calls[0]["task"]
    assert "no object detection" in calls[0]["role"]


def test_run_amenity_scan_runs_with_caveat_and_mismatch_skips(mock_api, monkeypatch):
    models, _ = mock_api
    models["GymScan0002"] = {"core": _core("GymScan0002", "Fitness Center", 29.85058, -95.53322, ["fitness_sports"])}
    models["FarScan0002"] = {"core": _core("FarScan0002", "Other building", 29.70, -95.30)}
    calls: list = []
    monkeypatch.setattr(matterport_agent, "run_agent", _fake_run_agent(calls))
    monkeypatch.setattr(scan_identity, "costar_candidates", lambda prop: [])
    rep = asyncio.run(matterport_agent.run(_ctx({**PROP, "id": "p-gym", "matterport_model_id": "GymScan0002"})))
    assert rep.status == "completed" and "AMENITY" in calls[0]["task"] and rep.summary.startswith("The linked scan appears to show a building amenity")
    ctx = _ctx({**PROP, "id": "p-far", "matterport_model_id": "FarScan0002"})
    rep = asyncio.run(matterport_agent.run(ctx))
    assert rep.status == "skipped" and "doesn't show this building" in rep.summary and len(calls) == 1
    assert ctx.shared["scan_identity"]["verdict"] == "mismatch" and "interior_facts" not in ctx.shared


def test_run_switches_auto_linked_amenity_scan(mock_api, monkeypatch):
    models, _ = mock_api
    models["GymScan0003"] = {"core": _core("GymScan0003", "Fitness Center", 29.85058, -95.53322, ["fitness_sports"])}
    models[LIVE_ID] = {"core": LIVE_CORE, "pi": LIVE_PI}
    calls: list = []
    monkeypatch.setattr(matterport_agent, "run_agent", _fake_run_agent(calls))
    monkeypatch.setattr(scan_identity, "costar_candidates", lambda prop: [{"id": LIVE_ID, "caption": None}])
    prop = {**PROP, "id": "p-auto", "matterport_model_id": "GymScan0003", "matterport_auto_model_id": "GymScan0003"}
    db.save_property(prop, None)
    rep = asyncio.run(matterport_agent.run(_ctx(prop)))
    assert rep.summary.startswith(f"Analyzed scan 'Northwest Trade Center - 9750 Tanner Rd' ({LIVE_ID})")
    assert db.get_property("p-auto")[0]["matterport_model_id"] == "GymScan0003"  # the stored link (and the tour the user sees) is unchanged
    # a user-set link (no auto marker) is analyzed as linked and never rewritten
    user = {**PROP, "id": "p-user", "matterport_model_id": "GymScan0003"}
    db.save_property(user, None)
    rep = asyncio.run(matterport_agent.run(_ctx(user)))
    assert db.get_property("p-user")[0]["matterport_model_id"] == "GymScan0003" and "amenity" in rep.summary


# ---------------------------------------------------------------- live client: errors, retry, tiers

def test_error_codes_map_to_clear_messages(mock_api):
    with pytest.raises(matterport.MatterportError) as err:
        asyncio.run(matterport.fetch_model("NoSuchScan1", use_cache=False))
    assert err.value.code == "not.found" and "isn't shared with this token" in str(err.value)
    for code, phrase in [("model.inactive", "archived"), ("quota.exceeded", "quota"), ("request.unauthorized", "not allowed")]:
        msg, c = matterport.error_message({"message": "x", "extensions": {"code": code}}, "this scan", "abc")
        assert c == code and phrase in msg


def test_unauthenticated_and_retry(fixture_dir, monkeypatch):
    monkeypatch.setattr(settings, "matterport_api_key", "id")
    monkeypatch.setattr(settings, "matterport_api_secret", "secret")
    monkeypatch.setattr(matterport, "RETRY_BACKOFF_S", 0)
    calls = {"core": 0}
    mode = {"auth": False}

    def handler(req: httpx.Request) -> httpx.Response:
        if mode["auth"]:
            return httpx.Response(401, json={})
        body = json.loads(req.content)
        if "TurnkeyModelCore" in body["query"]:
            calls["core"] += 1
            if calls["core"] == 1:  # transient: the API says retry
                return httpx.Response(200, json={"errors": [{"message": "busy", "extensions": {"code": "error.internal", "retry": "true", "httpCode": 503}}]})
            return httpx.Response(200, json={"data": {"model": LIVE_CORE}})
        return httpx.Response(503, json={})  # PI tier down (retried once, then given up)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    raw = asyncio.run(matterport.fetch_model("RetryScan01", use_cache=False))
    assert calls["core"] == 2 and raw["core"]["name"].startswith("Northwest") and raw["insights"] is None
    assert raw["tiers"] == {"core": True, "pi": False} and "unavailable" in raw["insights_note"]
    mode["auth"] = True
    with pytest.raises(matterport.MatterportError) as err:
        asyncio.run(matterport.fetch_model("AuthScan001", use_cache=False))
    assert err.value.code == "request.unauthenticated"


def test_pi_validation_error_keeps_core(mock_api, monkeypatch):
    models, _ = mock_api
    models["CoreOnly001"] = {"core": LIVE_CORE}
    invalid = {"message": "Validation error: Field 'boundary' undefined", "extensions": {"code": "request.invalid", "retry": "false", "httpCode": 400}}
    real = matterport.post_graphql

    async def pi_invalid(client, query, variables=None):
        if "TurnkeyModelInsights" in query:
            return {"errors": [invalid]}
        return await real(client, query, variables)

    monkeypatch.setattr(matterport, "post_graphql", pi_invalid)
    raw = asyncio.run(matterport.fetch_model("CoreOnly001", use_cache=False))
    s = matterport.summarize(raw)
    assert raw["insights"] is None and "invalid" in raw["insights_note"] and len(s["rooms"]) == 7 and s["tiers_available"] == ["core"]


def test_queries_use_current_fields():
    assert "mattertagsWithType" in matterport.CORE_QUERY and "mattertags {" not in matterport.CORE_QUERY
    assert "classifications" not in matterport.CORE_QUERY and "classifications" in matterport.PI_QUERY
    assert "objectAnnotations" not in matterport.CORE_QUERY + matterport.PI_QUERY


def test_validation_error_without_code_is_request_invalid():
    msg, code = matterport.error_message({"message": "Validation error (FieldUndefined@[model/bogus])", "extensions": {"classification": "ValidationError"}}, "this scan")
    assert code == "request.invalid" and "removed or renamed" in msg


def test_zero_width_openings_are_ignored():
    pi = json.loads(json.dumps(LIVE_PI))
    pi["rooms"][2]["boundary"]["edges"][1]["openings"].append({"type": "opening", "width": 0.004, "height": 2.4})  # observed artefact
    f = matterport.interior_facts(matterport.summarize({**LIVE_RAW, "insights": pi}))
    assert f["narrowest_door_in"] == 30 and len(f["doorways"]) == 4


def test_apartment_unit_tours_are_never_the_commercial_space():
    assert scan_identity.looks_like_residential("1BR, 1BA - 1x1 Traditional") and scan_identity.looks_like_residential("2BR, 2BA - 1,834SF")
    assert not scan_identity.looks_like_residential("Suite 855") and not scan_identity.looks_like_residential("Retail Space - 1st Floor")
    rec = {"matterport_scans": [{"id": "AAAAAAAAAAA", "caption": "1BR, 1BA"}, {"id": "BBBBBBBBBBB", "caption": "2BR, 2BA"}]}
    assert scan_identity.default_scan(rec) is None
    unit = scan_identity.assess("x", {"name": "1BR, 1BA - 1x1 Traditional", "lat": 29.85058, "lon": -95.53322}, PROP)
    assert unit["verdict"] == "residential" and "apartment" in unit["reason"]


def test_search_results_shape_summarizes():
    """Model search results give floors as {"count": n} and no processing date; summarize must cope."""
    core = {"id": "x", "name": "Suite 1080", "state": "active", "floors": {"count": 2}, "address": {"address": "1301 Fannin"}, "geolocation": {"lat": "29.75", "long": "-95.36"}}
    ident = matterport.summarize({"model_id": "x", "core": core})["identity"]
    assert ident["floor_count"] == 2 and ident["name"] == "Suite 1080" and ident["lat"] == 29.75
    assert "floors { count }" in scan_identity.SEARCH_QUERY and "floors { id }" not in scan_identity.SEARCH_QUERY
