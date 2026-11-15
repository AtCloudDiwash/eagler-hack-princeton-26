"""Live building tour lookup (services/suite_tours.py), tested offline with recorded API shapes."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import pytest  # noqa: E402

from config import settings  # noqa: E402
from services import matterport, suite_tours  # noqa: E402

PROP = {"id": "b", "lat": 29.75352, "lon": -95.36577, "address": "1301 Fannin St, Houston, TX", "costar_id": 233968}
REC = {"id": 233968, "matterport_scans": [{"id": "RW7cKwVEpiJ", "caption": "Lobby Matterport"}]}


def _model(mid, name, line2, lat, lon):
    return {"id": mid, "name": name, "state": "active", "internalId": "", "description": "", "address": {"streetAddressLines": ["1301 Fannin", line2]}, "geolocation": {"lat": str(lat), "long": str(lon)}}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(settings, "matterport_api_key", "id")
    monkeypatch.setattr(settings, "matterport_api_secret", "secret")
    seen = []

    async def fake(client, query, variables=None):
        seen.append(query)
        if "TurnkeyBuildingTours" in query:
            assert "floors { count }" in query and 'model(id: "RW7cKwVEpiJ") {' in query
            k0 = query.split('k0: model(id: "RW7cKwVEpiJ") {')[1].split("}")[0]
            assert "floors { count" not in k0  # full models have a floor list, not a count
            return {"data": {"byId": {"results": []}, "byAddress": {"results": [
                {**_model("oKkUgjXNF3h", "1301 Fannin, Suite 1080", "1080", 29.75398, -95.36634), "floors": {"count": 1}},
                {**_model("FarAwayScn1", "1301 Fannin, Suite 9", "9", 29.80, -95.40), "floors": {"count": 1}},
            ]}, "k0": {**_model("RW7cKwVEpiJ", "1301 Fannin, Lobby", "Lobby", 29.75395, -95.36544), "floors": [{"id": "f"}]}}}
        return {"data": {"d0": {"processing": {"processingCompletedAt": "2020-04-09T00:00:00Z"}}, "d1": {"processing": {"processingCompletedAt": "2021-02-06T00:00:00Z"}, "dimensionEstimates": {"areaIndoor": 4600.0}}}}

    monkeypatch.setattr(matterport, "post_graphql", fake)
    return seen


def test_building_tours_labels_and_filters(api):
    tours = asyncio.run(suite_tours.building_tours(PROP, REC, use_cache=False))
    by = {t["id"]: t for t in tours}
    assert set(by) == {"RW7cKwVEpiJ", "oKkUgjXNF3h"}  # the address hit 6 km away is dropped
    assert by["RW7cKwVEpiJ"]["kind"] == "common area" and by["RW7cKwVEpiJ"]["captured"] == "2020-04-09"
    assert by["oKkUgjXNF3h"]["suites"] == ["1080"] and by["oKkUgjXNF3h"]["floor"] == 10 and by["oKkUgjXNF3h"]["area_sqft"] == 4600


def test_match_only_the_listed_suite(api):
    tours = asyncio.run(suite_tours.building_tours(PROP, REC, use_cache=False))
    none = suite_tours.for_property(tours, {"suite": "170", "sqft": 1587}, None)
    assert none["match"] is None and "No 3D tour of Suite 170" in none["note"]
    assert "not your suite" in next(t for t in none["tours"] if t["id"] == "oKkUgjXNF3h")["chips"]
    hit = suite_tours.for_property(tours, {"suite": "Suite 1080", "sqft": 5482}, None)
    assert hit["match"]["id"] == "oKkUgjXNF3h" and hit["match"]["confidence"] == "strong"  # 4,600 / 5,482 = 0.84
    assert any("previous tenant" in c for c in hit["match"]["caveats"])  # captured 2021
    assert hit["tours"][0]["id"] == "oKkUgjXNF3h" and "your suite" in hit["tours"][0]["chips"]


def test_area_mismatch_downgrades_and_tokens_normalize():
    assert suite_tours.suite_tokens("1500 - Wells Fargo Plaza") == ["1500"] and suite_tours.suite_tokens("Ste. 0328") == ["328"]
    tours = [{"id": "x", "name": "Suite 1009 - 2,400SF", "suites": ["1009"], "area_sqft": 2300, "captured": "2025-01-01", "age_years": 0.9, "caption_conflict": None, "kind": "suite"}]
    m = suite_tours.match(tours, {"suite": "1009", "sqft": 5525})
    assert m["confidence"] == "possible" and "layout may have changed" in m["caveats"][0]


def test_suite_number_does_not_verify_an_apartment_amenity_or_other_building():
    base = {"id": "x", "name": "Suite 170", "suites": ["170"], "kind": "suite", "distance_m": 10}
    for changes in ({"kind": "apartment"}, {"kind": "common area"}, {"distance_m": 3000}):
        assert suite_tours.match([{**base, **changes}], {"suite": "170"}) is None
    uncertain = suite_tours.for_property([{**base, "suites": ["170", "180"]}], {"suite": "170"}, None)
    assert uncertain["match"]["confidence"] == "possible"
    assert "possible suite match" in uncertain["tours"][0]["chips"]
    assert "your suite" not in uncertain["tours"][0]["chips"]


def test_partial_graphql_results_are_not_cached(api, monkeypatch):
    real_post = matterport.post_graphql
    cached = []

    async def partial(client, query, variables=None):
        body = await real_post(client, query, variables)
        body["errors"] = [{"message": "One model temporarily unavailable"}]
        return body

    monkeypatch.setattr(matterport, "post_graphql", partial)
    monkeypatch.setattr(suite_tours.db, "cache_set", lambda *args: cached.append(args))
    tours = asyncio.run(suite_tours.building_tours(PROP, REC, use_cache=False))
    assert len(tours) == 2
    assert not cached


def test_manual_tour_choice_and_unlink_survive_search(monkeypatch):
    import db
    import main

    tour = {"id": "Matched1234", "name": "Suite 170", "suites": ["170"], "kind": "suite", "distance_m": 10}

    async def building_tours(*args):
        return [tour]

    monkeypatch.setattr(suite_tours, "building_tours", building_tours)
    monkeypatch.setattr(main.costar, "match", lambda *args: None)
    candidate = {**PROP, "id": "suite-choice-test", "best_space": {"suite": "170"}}
    manual = {**candidate, "matterport_model_id": "Manual12345", "matterport_user_linked": True, "matterport_auto_model_id": None}
    db.save_property(manual, None)
    db.save_property(candidate, None)
    stored, raw = db.get_property(candidate["id"])
    prop, view = asyncio.run(main._suite_tours(stored, raw, None))
    assert prop["matterport_model_id"] == "Manual12345"
    assert view["match"]["id"] == tour["id"]
    asyncio.run(main.unlink_matterport(candidate["id"]))
    db.save_property(candidate, None)
    stored, raw = db.get_property(candidate["id"])
    prop, _ = asyncio.run(main._suite_tours(stored, raw, None))
    assert prop["matterport_model_id"] is None and prop["matterport_user_unlinked"]


def test_resolved_selection_is_used_for_tour_label(monkeypatch):
    from schemas import Intent
    from services import costar

    tours = [{"id": "Chosen12345", "name": "Suite 1080", "suites": ["1080"], "kind": "suite", "distance_m": 10}]
    async def building_tours(*args):
        return tours
    monkeypatch.setattr(suite_tours, "building_tours", building_tours)
    monkeypatch.setattr(costar, "match", lambda *args: REC)
    def unexpected_reselection(*args):
        raise AssertionError("A resolved selection must not be rebuilt from thin sizing params")
    monkeypatch.setattr(costar, "candidate_fields", unexpected_reselection)
    prop = {**PROP, "_selection_resolved": True, "best_space": {"suite": "1080", "sqft": 5482},
            "matterport_user_unlinked": True}
    _, view = asyncio.run(suite_tours.resolve_property(prop, None, Intent(sqft=1200)))
    assert view["match"]["id"] == "Chosen12345"
    assert "your suite" in view["tours"][0]["chips"]
