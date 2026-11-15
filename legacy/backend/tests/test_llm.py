"""Local LLM (Ollama) integration: parser path, fallbacks, grounded ranking summary, health.

No network: httpx.get / httpx.post are replaced by a fake Ollama server. The live check against a
real Ollama is scripts/llm_live_check.py (not part of this suite)."""
from __future__ import annotations

import json

import httpx
import pytest
from conftest import ALL_IDS, DEMO_DETAILS, profile

from app.config import settings
from app.models import AnalyzeResponse
from app.providers import costar_provider
from app.services import llm, ranking_summary
from app.services import requirements_parser as rp
from app.services.agent_orchestrator import analyze_properties

OLLAMA = "http://ollama.test:11434"
_dumps = json.dumps  # FakeOllama.post's `json` parameter shadows the module


class FakeOllama:
    """Minimal /api/tags + /api/chat. `parse` / `summary` are the JSON payloads (or callables / errors)."""

    def __init__(self, models=("qwen3:8b",), parse=None, summary=None, content=None, done_reason="stop",
                 chat_error=None, tags_error=None, status=200):
        self.models, self.parse, self.summary, self.content = models, parse, summary, content
        self.done_reason, self.chat_error, self.tags_error, self.status = done_reason, chat_error, tags_error, status
        self.chats: list[dict] = []
        self.tag_calls = 0

    def get(self, url, **kwargs):
        assert url == f"{OLLAMA}/api/tags"
        self.tag_calls += 1
        if self.tags_error:
            raise self.tags_error
        body = {"models": [{"name": m, "model": m} for m in self.models]}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    def post(self, url, json=None, **kwargs):  # noqa: A002 - mirrors httpx.post
        assert url == f"{OLLAMA}/api/chat"
        self.chats.append(json)
        if self.chat_error:
            raise self.chat_error
        is_summary = "summary" in json["format"]["properties"]
        if self.content is not None:
            content = self.content
        else:
            payload = self.summary if is_summary else self.parse
            if callable(payload):
                payload = payload(json)
            content = _dumps(payload)
        body = {"model": json["model"], "message": {"role": "assistant", "content": content},
                "done": True, "done_reason": self.done_reason}
        return httpx.Response(self.status, json=body, request=httpx.Request("POST", url))


def grounded_summary(body: dict) -> dict:
    """A well-behaved model: quotes only digest strings."""
    digest = json.loads(body["messages"][1]["content"].split("\n", 1)[1])
    props = digest["properties"]
    top = props[0]
    return {
        "summary": f"{top['address']} ranks first with a first-year cost of {top['first_year_cost']}.",
        "per_property": [
            {"property_id": p["property_id"], "sentence": f"Rank {p['rank']}: {p['status']}, rent {p['monthly_rent']}."}
            for p in props
        ],
    }


PARSED = {"capacity": 40, "bathrooms": 2, "parking": None, "min_sqft": None, "max_sqft": None,
          "max_rent": 5000, "needs_kitchen": True}


@pytest.fixture
def fake_ollama(monkeypatch):
    def install(**kwargs) -> FakeOllama:
        fake = FakeOllama(**kwargs)
        monkeypatch.setattr(settings, "llm_provider", "ollama")
        monkeypatch.setattr(settings, "ollama_base_url", OLLAMA)
        monkeypatch.setattr(settings, "ollama_model", "qwen3:8b")
        monkeypatch.setattr(httpx, "get", fake.get)
        monkeypatch.setattr(httpx, "post", fake.post)
        return fake

    llm.reset_availability_cache()
    yield install
    llm.reset_availability_cache()


RAMEN = "Opening a ramen shop, about forty seats, need a full kitchen, two restrooms, budget under five grand a month"


# ------------------------------------ parser ------------------------------------


def test_parser_uses_ollama_result(fake_ollama):
    fake = fake_ollama(parse=PARSED)
    req, parser = rp.parse_requirements(profile(details=RAMEN))
    assert parser == "ollama"
    assert req.max_rent == 5000.0  # "five grand" -> only the LLM understood it
    assert (req.capacity, req.bathrooms_required, req.needs_kitchen) == (40, 2, True)
    body = fake.chats[0]
    assert body["model"] == "qwen3:8b" and body["stream"] is False and body["think"] is False
    assert body["options"]["temperature"] == 0 and body["keep_alive"] == settings.ollama_keep_alive
    assert set(body["format"]["required"]) == set(rp.RAW_FIELDS)


@pytest.mark.parametrize("kwargs", [
    {"chat_error": httpx.ReadTimeout("slow")},
    {"chat_error": httpx.ConnectError("connection refused")},
    {"content": "Sure! Here are the fields: capacity 40"},  # invalid JSON
    {"content": "[1, 2, 3]"},                               # JSON but not an object
    {"parse": PARSED, "done_reason": "length"},             # truncated
    {"parse": PARSED, "status": 500},
])
def test_parser_falls_back_to_regex(fake_ollama, kwargs):
    fake_ollama(**kwargs)
    req, parser = rp.parse_requirements(profile())
    assert parser == "regex"
    assert (req.capacity, req.bathrooms_required, req.parking_required) == (40, 2, 20)


def test_ollama_down_or_model_missing_skips_the_call(fake_ollama):
    fake = fake_ollama(tags_error=httpx.ConnectError("connection refused"))
    assert rp.parse_requirements(profile())[1] == "regex" and fake.chats == []
    llm.reset_availability_cache()
    fake = fake_ollama(models=("qwen3:14b",))
    assert rp.parse_requirements(profile())[1] == "regex" and fake.chats == []


def test_availability_is_cached_and_timeout_marks_unavailable(fake_ollama):
    fake = fake_ollama(chat_error=httpx.ReadTimeout("slow"))
    assert llm.is_available() and llm.is_available()
    assert fake.tag_calls == 1
    rp.parse_requirements(profile())
    assert llm.is_available() is False  # the summary call won't wait for a second timeout


def test_think_tags_are_stripped(fake_ollama):
    fake_ollama(content="<think>The user wants 40 seats...</think>\n" + json.dumps(PARSED))
    req, parser = rp.parse_requirements(profile(details=RAMEN))
    assert parser == "ollama" and req.max_rent == 5000.0
    assert llm.strip_think("<think>unterminated") == ""


# ------------------------------------ summary ------------------------------------


@pytest.fixture
def demo_response(monkeypatch) -> AnalyzeResponse:
    monkeypatch.setattr(settings, "llm_provider", "none")
    props = [costar_provider.get_property(pid) for pid in ALL_IDS]
    return analyze_properties(profile(details=DEMO_DETAILS), props)


def test_digest_is_compact_and_complete(demo_response):
    digest = ranking_summary.build_digest(demo_response)
    assert [p["rank"] for p in digest["properties"]] == [1, 2, 3, 4]
    for entry, result in zip(digest["properties"], demo_response.results):
        assert entry["property_id"] == result.property_id and entry["fit_score"] == round(result.score)
        assert entry["status"] in {"qualifies", "weak fit", "disqualified"}
        if result.disqualified:
            assert entry["disqualified_by"]
    assert len(json.dumps(digest)) < 12_000


def _summary(digest, text, per_property=None):
    per_property = per_property if per_property is not None else [
        {"property_id": p["property_id"], "sentence": "Fine."} for p in digest["properties"]
    ]
    return {"summary": text, "per_property": per_property}


def test_guardrail_accepts_digest_numbers(demo_response):
    digest = ranking_summary.build_digest(demo_response)
    top = digest["properties"][0]
    rent = float(top["monthly_rent"].strip("$").replace(",", ""))
    text = (f"{top['address']} is the best pick at {top['first_year_cost']} in the first year, "
            f"with rent of about ${round(rent / 1000)}k and a fit score of {top['fit_score']}.")
    summary = ranking_summary.validate_summary(_summary(digest, text), digest, "ollama:qwen3:8b")
    assert summary.grounded is True and summary.model == "ollama:qwen3:8b"
    assert set(summary.per_property) == set(ALL_IDS)


@pytest.mark.parametrize("text", [
    "The top pick saves you $123,457 compared to the others.",  # invented dollar figure
    "Expect to spend about $9.9 million.",                      # invented, with suffix
    "The top pick scores 99 out of 100.",                       # invented score
    "It is a strong option with a 93 fit score.",
])
def test_guardrail_rejects_invented_numbers(demo_response, text):
    digest = ranking_summary.build_digest(demo_response)
    with pytest.raises(ValueError, match="ungrounded"):
        ranking_summary.validate_summary(_summary(digest, text), digest, "m")


def test_guardrail_rejects_unknown_property_ids(demo_response):
    digest = ranking_summary.build_digest(demo_response)
    bad = _summary(digest, "All good.", [{"property_id": "property-999", "sentence": "Great."}])
    with pytest.raises(ValueError, match="unknown property id"):
        ranking_summary.validate_summary(bad, digest, "m")


def test_summary_attached_to_analysis(fake_ollama):
    fake = fake_ollama(parse=PARSED, summary=grounded_summary)
    props = [costar_provider.get_property(pid) for pid in ALL_IDS]
    response = analyze_properties(profile(details=RAMEN), props)
    assert response.mode["parser"] == "ollama" and response.mode["llm"] == "ollama:qwen3:8b"
    assert response.ai_summary is not None and response.ai_summary.grounded
    assert response.results[0].address in response.ai_summary.text
    assert set(response.ai_summary.per_property) == set(ALL_IDS)
    assert len(fake.chats) == 2  # one parse + exactly one summary call
    assert fake.chats[1]["format"]["properties"]["per_property"]["items"]["properties"]["property_id"]["enum"] == [
        r.property_id for r in response.results
    ]


def test_ungrounded_summary_becomes_null_but_ranking_is_unchanged(fake_ollama, demo_response):
    fake_ollama(parse=PARSED, summary={"summary": "Pick the first one and save $1,234,567.", "per_property": []})
    props = [costar_provider.get_property(pid) for pid in ALL_IDS]
    response = analyze_properties(profile(details=DEMO_DETAILS), props)
    assert response.ai_summary is None
    assert response.mode["llm"] == "ollama:qwen3:8b"  # the parser still used it
    assert [r.property_id for r in response.results] == [r.property_id for r in demo_response.results]
    assert [r.score for r in response.results] == [r.score for r in demo_response.results]


def test_no_llm_means_null_summary_and_no_calls(monkeypatch, demo_response):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("no LLM call with LLM_PROVIDER=none"))
    monkeypatch.setattr(httpx, "get", lambda *a, **k: pytest.fail("no LLM call with LLM_PROVIDER=none"))
    assert ranking_summary.summarize_ranking(demo_response) is None
    assert demo_response.ai_summary is None and demo_response.mode["llm"] == "none"


def test_old_runs_default_to_null_summary(demo_response):
    stored = json.loads(demo_response.model_dump_json())
    stored.pop("ai_summary")
    assert AnalyzeResponse.model_validate(stored).ai_summary is None


# ------------------------------------ API ------------------------------------

BODY = {"business_profile": {"type": "restaurant", "details": DEMO_DETAILS, "city": "Austin", "state": "TX"},
        "property_ids": ALL_IDS}


def test_analyze_succeeds_when_ollama_is_down(client, fake_ollama):
    fake_ollama(tags_error=httpx.ConnectError("connection refused"))
    response = client.post("/api/v1/analyze", json=BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["ai_summary"] is None
    assert (body["mode"]["parser"], body["mode"]["llm"]) == ("regex", "none")


def test_analyze_stores_ai_summary(client, fake_ollama):
    fake_ollama(parse=PARSED, summary=grounded_summary)
    body = client.post("/api/v1/analyze", json=BODY).json()
    assert body["ai_summary"]["model"] == "ollama:qwen3:8b" and body["ai_summary"]["grounded"] is True
    stored = client.get(f"/api/v1/analyses/{body['analysis_id']}").json()
    assert stored["ai_summary"] == body["ai_summary"]


def test_health_reports_llm(client, fake_ollama):
    fake_ollama()
    mode = client.get("/health").json()["mode"]
    assert (mode["parser"], mode["llm"]) == ("ollama", "ollama:qwen3:8b")
    llm.reset_availability_cache()
    fake_ollama(tags_error=httpx.ConnectError("connection refused"))
    mode = client.get("/health").json()["mode"]
    assert (mode["parser"], mode["llm"]) == ("regex", "none")
