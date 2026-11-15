"""Shared fixtures. Environment is pinned *before* the app is imported so tests never touch the
network (no API keys, mock providers) or the developer's real SQLite file."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="turnkey-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["USE_MOCK_DATA"] = "true"
os.environ["LLM_PROVIDER"] = "none"  # tests that need an LLM install a fake one (tests/test_llm.py)
for _key in ("ANTHROPIC_API_KEY", "COSTAR_API_KEY", "MATTERPORT_API_KEY", "VEXCEL_API_KEY", "CRITERIA_PATH"):
    os.environ[_key] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import business_types, jurisdiction_for  # noqa: E402
from app.models import BusinessProfile, Criterion, Evidence, Property  # noqa: E402
from app.services.compliance_engine import build_inputs  # noqa: E402
from app.services.evaluators import EvalContext  # noqa: E402
from app.services.requirements_parser import build_requirements  # noqa: E402

DEMO_DETAILS = "40 seats, kitchen needed, 2 bathrooms, 20 parking spaces"
ALL_IDS = ["property-123", "property-456", "property-789", "property-321"]


@pytest.fixture(autouse=True)
def isolated_vexcel_cache(tmp_path, monkeypatch):
    """Live-mode tests must never read or write the real backend/static/vexcel-cache."""
    from app.providers import vexcel_provider

    monkeypatch.setattr(vexcel_provider, "CACHE_DIR", tmp_path / "vexcel-cache")
    vexcel_provider.clear_failure_cache()
    yield
    vexcel_provider.clear_failure_cache()


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def profile(business_type: str = "restaurant", details: str = DEMO_DETAILS, city="Austin", state="TX"):
    return BusinessProfile(type=business_type, details=details, city=city, state=state)


@pytest.fixture
def restaurant_req():
    return build_requirements(profile(), {"capacity": 40, "bathrooms": 2, "parking": 20, "needs_kitchen": True})


def make_property(**overrides) -> Property:
    data = dict(
        id="property-test", address="1 Test St", city="Austin", state="TX", zip="78701",
        size_sqft=2000, rent=4000, zoning="GR", previous_use=None, ti_allowance_per_sqft=0,
    )
    data.update(overrides)
    return Property(**data)


def obs(source: str = "matterport", **facts) -> dict[str, Evidence]:
    return {k: Evidence(key=k, value=v, source=source) for k, v in facts.items()}


def make_criterion(**overrides) -> Criterion:
    data = dict(id="test_criterion", description="Test", domain="space", weight=10, evaluator="parking_checker")
    data.update(overrides)
    return Criterion(**data)


def make_ctx(criterion: Criterion, requirements, prop: Property | None = None, observations=None,
             city="Austin", state="TX", business=None) -> EvalContext:
    prop = prop or make_property(city=city, state=state)
    observations = observations or {}
    return EvalContext(
        requirements=requirements,
        property=prop,
        observations=observations,
        criterion=criterion,
        jurisdiction=jurisdiction_for(city, state),
        business=business or business_types()[requirements.business_type],
        inputs=build_inputs(requirements, prop, observations),
    )
