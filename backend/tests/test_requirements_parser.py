from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from conftest import DEMO_DETAILS, profile

from app.config import settings
from app.services import requirements_parser as rp


@pytest.mark.parametrize(
    "text, expected",
    [
        (DEMO_DETAILS, {"capacity": 40, "bathrooms": 2, "parking": 20, "needs_kitchen": True}),
        ("40-seat bistro", {"capacity": 40}),
        ("4 chairs, two restrooms", {"capacity": 4, "bathrooms": 2}),
        ("seating for 60 and parking for 12", {"capacity": 60, "parking": 12}),
        ("1500-2500 sq ft", {"min_sqft": 1500, "max_sqft": 2500}),
        ("at least 1,800 square feet", {"min_sqft": 1800}),
        ("up to 3000 sqft", {"max_sqft": 3000}),
        ("budget $5k/month", {"max_rent": 5000.0}),
        ("rent under $6,500", {"max_rent": 6500.0}),
        ("no kitchen needed", {"needs_kitchen": False}),
    ],
)
def test_regex_extracts_fields(text, expected):
    found = rp.regex_extract(text)
    for key, value in expected.items():
        assert found[key] == value, (text, found)


def test_sqft_is_not_mistaken_for_rent():
    found = rp.regex_extract("under 2000 sq ft")
    assert found.get("max_sqft") == 2000
    assert "max_rent" not in found


def test_demo_profile_uses_stated_values():
    req, parser = rp.parse_requirements(profile())
    assert parser == "regex"
    assert (req.capacity, req.bathrooms_required, req.parking_required) == (40, 2, 20)
    assert req.parking_source == "user"
    assert req.needs_kitchen is True
    assert req.occupant_load == 46  # 40 seats + 2 staff + 0.1 * 40
    assert req.capacity_unit == "seats"
    assert req.required_electrical_amps == 400
    assert req.required_hvac_tons == 7.0  # 40 * 35 sq ft / 200 sq ft per ton


def test_defaults_are_recorded_as_assumptions():
    req, _ = rp.parse_requirements(profile(details=""))
    assert req.capacity == 40
    assert req.parking_source == "guideline"
    assert req.parking_required == 14  # ceil(40 * 0.33)
    assert req.bathrooms_required == 2  # 46 occupants > 15 single-user limit
    text = " ".join(req.assumptions)
    for fragment in ("Capacity not stated", "Parking not stated", "Restrooms not stated", "kitchen", "HVAC", "Electrical"):
        assert fragment in text


def test_dental_defaults():
    req, _ = rp.parse_requirements(profile("dental_clinic", "4 chairs"))
    assert req.capacity_unit == "chairs"
    assert req.needs_kitchen is False
    assert req.parking_required == 12  # 4 chairs * 3
    assert req.occupant_load == 16  # 4*2 + 2 + 1.5*4


def test_unknown_business_type():
    with pytest.raises(rp.UnknownBusinessType):
        rp.parse_requirements(profile("bowling_alley"))


# ------------------------- Claude path (always mocked) -------------------------


class FakeMessages:
    def __init__(self, payload=None, error=None, stop_reason="end_turn"):
        self.payload, self.error, self.stop_reason = payload, error, stop_reason
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        text = json.dumps(self.payload)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture
def fake_claude(monkeypatch):
    def install(**kwargs) -> FakeMessages:
        messages = FakeMessages(**kwargs)
        monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
        monkeypatch.setattr(rp, "_anthropic_client", lambda: SimpleNamespace(messages=messages))
        return messages

    return install


def test_claude_fields_merge_over_regex(fake_claude):
    messages = fake_claude(payload={
        "capacity": 55, "bathrooms": None, "parking": 25, "min_sqft": 1500, "max_sqft": 2500,
        "max_rent": 6000, "needs_kitchen": True,
    })
    req, parser = rp.parse_requirements(profile(details="room for about 55 diners, 2 bathrooms, 25 cars"))
    assert parser == "claude"
    assert req.capacity == 55
    assert req.bathrooms_required == 2  # Claude returned null -> regex value kept
    assert req.parking_required == 25 and req.parking_source == "user"
    assert (req.min_sqft, req.max_sqft, req.max_rent) == (1500, 2500, 6000.0)
    call = messages.calls[0]
    assert call["model"] == settings.anthropic_model
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert set(call["output_config"]["format"]["schema"]["required"]) == set(rp.RAW_FIELDS)


def test_claude_invalid_values_are_dropped(fake_claude):
    fake_claude(payload={
        "capacity": -3, "bathrooms": "two", "parking": 99999, "min_sqft": 3000, "max_sqft": 1000,
        "max_rent": None, "needs_kitchen": "yes",
    })
    req, parser = rp.parse_requirements(profile())
    assert parser == "claude"
    assert (req.capacity, req.bathrooms_required, req.parking_required) == (40, 2, 20)  # regex values
    assert req.min_sqft is None and req.max_sqft is None


@pytest.mark.parametrize("error", [TimeoutError("slow"), RuntimeError("boom"), ValueError("bad json")])
def test_claude_failure_falls_back_to_regex(fake_claude, error):
    fake_claude(error=error)
    req, parser = rp.parse_requirements(profile())
    assert parser == "regex"
    assert req.capacity == 40 and req.parking_required == 20


def test_claude_refusal_falls_back_to_regex(fake_claude):
    fake_claude(payload={}, stop_reason="refusal")
    _, parser = rp.parse_requirements(profile())
    assert parser == "regex"


def test_no_key_never_calls_claude(monkeypatch):
    def explode():
        raise AssertionError("Claude must not be called without a key")

    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(rp, "_anthropic_client", explode)
    _, parser = rp.parse_requirements(profile())
    assert parser == "regex"
