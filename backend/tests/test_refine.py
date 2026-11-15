"""Refining a search in conversation (services/refine.py), offline: a scripted model or the rules fallback."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import pytest  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402

from schemas import Budget, Intent, Need  # noqa: E402
from services import refine  # noqa: E402


def _prev() -> Intent:
    return Intent(business_type="restaurant", business_label="Restaurant", location_text="Houston", seats=40, occupancy={"seats": 40},
                  needs=[Need(id="parking", label="On-site parking", priority="must")], requirements=["on-site parking"])


class _Fake:
    def __init__(self, out: Any = None, error: Exception | None = None) -> None:
        self.out, self.error = out, error

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        async def run(_: Any) -> Any:
            if self.error:
                raise self.error
            return schema.model_validate(self.out)
        return RunnableLambda(lambda _: None, afunc=run)


def _refined(**over: Any) -> dict:
    base = {"business_type": "restaurant", "location": "Houston", "seats": 40, "sqft": None, "size_counts": {"seats": 40}, "must_have": ["parking"],
            "nice_to_have": [], "requirements": [], "action": "refine", "reply": "Done.", "drop_needs": []}
    return {**base, **over}


def test_follow_up_changes_only_what_the_user_mentioned(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(refine, "chat_model", lambda *a, **k: _Fake(_refined(seats=60, size_counts={"seats": 60}, budget_amount=8000, budget_period="monthly", reply="Bumped to 60 seats with an $8k/month budget.")))
    out = asyncio.run(refine.refine(_prev(), "make it 60 seats, budget 8k a month"))
    new = out["intent"]
    assert out["action"] == "refine" and new.seats == 60 and new.budget.amount == 8000 and new.location_text == "Houston"
    assert [n.id for n in new.needs] == ["parking"]  # untouched must-have kept
    assert "60 seats" in out["changes"] and any(c.startswith("Budget $8,000") for c in out["changes"])


def test_dropping_a_need_and_questions_dont_re_search(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(refine, "chat_model", lambda *a, **k: _Fake(_refined(must_have=[], drop_needs=["parking"])))
    out = asyncio.run(refine.refine(_prev(), "actually I don't need parking"))
    assert out["action"] == "refine" and out["intent"].needs == [] and "− On-site parking" in out["changes"]
    monkeypatch.setattr(refine, "chat_model", lambda *a, **k: _Fake(_refined(action="answer", reply="1301 Fannin St has a ground-floor suite.")))
    q = asyncio.run(refine.refine(_prev(), "which ones are on the ground floor?", matches=[{"title": "1301 Fannin St"}]))
    assert q["action"] == "answer" and q["intent"] == _prev() and "1301 Fannin" in q["reply"]


def test_a_refine_that_changes_nothing_becomes_an_answer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(refine, "chat_model", lambda *a, **k: _Fake(_refined(reply="That's already your search.")))
    out = asyncio.run(refine.refine(_prev(), "a restaurant in Houston please"))
    assert out["action"] == "answer" and out["changes"] == []


def test_rules_fallback_when_no_llm(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(refine, "chat_model", lambda *a, **k: _Fake(error=RuntimeError("all providers down")))
    out = asyncio.run(refine.refine(_prev(), "make it 2,500 sq ft with a budget of $9k/month"))
    new = out["intent"]
    assert out["action"] == "refine" and new.sqft == 2500 and new.budget and new.budget.amount == 9000 and new.seats == 40
    assert "quick parser" in out["reply"]


def test_describe_changes_is_deterministic():
    prev = _prev()
    new = prev.model_copy(update={"location_text": "Midtown, Houston", "budget": Budget(amount=6000, period="monthly"), "tenure": "buy"})
    assert refine.describe_changes(prev, new) == ["Area: Midtown, Houston", "Budget $6,000 monthly", "Buying"]
    assert refine.describe_changes(prev, prev) == []


def test_free_text_that_restates_a_need_is_dropped(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(refine, "chat_model", lambda *a, **k: _Fake(_refined(must_have=["parking", "ground_floor"], requirements=["ground floor spaces only", "outdoor music allowed"])))
    new = asyncio.run(refine.refine(_prev(), "only ground floor"))["intent"]
    assert "ground floor spaces only" not in new.requirements and "outdoor music allowed" in new.requirements


def test_budget_refine_preserves_concept_hint_and_bounds(monkeypatch):
    from services.intent import parse_rules
    from services import sizing
    prev = parse_rules("small coffee shop, at least 1,200 sq ft")
    monkeypatch.setattr(refine, "chat_model", lambda: _Fake(_refined(
        seats=None, size_counts={}, budget_amount=8000, budget_period="monthly")))
    result = asyncio.run(refine.refine(prev, "budget $8k"))
    new = result["intent"]
    assert new.budget.amount == 8000
    assert (new.concept, new.size_hint, new.sqft_min, new.sqft_max) == (prev.concept, prev.size_hint, prev.sqft_min, prev.sqft_max)
    assert sizing.estimate(new) == sizing.estimate(prev)


def test_free_text_only_is_saved_and_reported_honestly(monkeypatch):
    monkeypatch.setattr(refine, "chat_model", lambda: _Fake(_refined(requirements=["outdoor music allowed"])))
    result = asyncio.run(refine.refine(_prev(), "outdoor music allowed"))
    assert result["action"] == "refine"
    assert "outdoor music allowed" in result["intent"].requirements
    assert "do not affect discovery ranking" in result["reply"]
    assert any("check during analysis" in c for c in result["changes"])


def test_omitted_fields_survive_patch():
    prev = _prev().model_copy(update={"budget": Budget(amount=6000, period="monthly"), "near": ["Rice"]})
    out = refine._Refinement(business_type="restaurant", location="Houston", action="refine", reply="Done", budget_amount=8000, budget_period="monthly")
    new = refine._intent_from(out, prev)
    assert new.needs == prev.needs and new.occupancy == prev.occupancy
    assert new.near == ["Rice"] and new.budget.amount == 8000


def test_null_optional_size_fields_do_not_erase_request(monkeypatch):
    from services.intent import parse_rules
    prev = parse_rules("small coffee shop, at least 1,200 sq ft")
    monkeypatch.setattr(refine, "chat_model", lambda: _Fake(_refined(
        concept=None, size_hint=None, sqft_min=None, sqft_max=None,
        budget_amount=8000, budget_period="monthly", seats=None, size_counts={})))
    new = asyncio.run(refine.refine(prev, "budget $8k"))["intent"]
    assert (new.concept, new.size_hint, new.sqft_min) == (prev.concept, prev.size_hint, 1200)
    new = asyncio.run(refine.refine(prev, "instead 900 sq ft"))["intent"]
    assert new.sqft == 900 and new.sqft_min is None and new.sqft_max is None
