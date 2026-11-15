"""Live contract test: the CORE and PI queries must still pass Matterport's GraphQL validation.

Validation is all-or-nothing, so one deprecated/removed field silently empties a whole tier. This runs the
real queries against the Matterport sandbox demo model, and ONLY when sandbox credentials are set:
    MATTERPORT_SANDBOX_API_KEY=... MATTERPORT_SANDBOX_API_SECRET=... .venv/bin/python -m pytest -q tests/test_matterport_contract.py
Plan-gated fields may come back unauthorized on the sandbox; that is fine. Validation errors are not.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import httpx  # noqa: E402
import pytest  # noqa: E402

from config import settings  # noqa: E402
from services import matterport, scan_identity  # noqa: E402

KEY, SECRET = os.environ.get("MATTERPORT_SANDBOX_API_KEY"), os.environ.get("MATTERPORT_SANDBOX_API_SECRET")
pytestmark = pytest.mark.skipif(not (KEY and SECRET), reason="set MATTERPORT_SANDBOX_API_KEY / MATTERPORT_SANDBOX_API_SECRET to run the live contract test")

DEMO_QUERY = "{ models(query: \"*\", include: [demo], pageSize: 5) { results { id demo state } } }"


def _validation_errors(body: dict) -> list[str]:
    out = []
    for e in body.get("errors") or []:
        ext = e.get("extensions") or {}
        if ext.get("code") == "request.invalid" or "validation" in str(ext.get("classification", "")).lower() or "validation" in (e.get("message") or "").lower():
            out.append(e.get("message", ""))
    return out


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setattr(settings, "matterport_api_key", KEY)
    monkeypatch.setattr(settings, "matterport_api_secret", SECRET)
    monkeypatch.setattr(matterport, "RETRY_BACKOFF_S", 1.0)


async def _demo_model_id(client: httpx.AsyncClient) -> str:
    body = await matterport.post_graphql(client, DEMO_QUERY)
    assert not _validation_errors(body), body
    results = ((body.get("data") or {}).get("models") or {}).get("results") or []
    demo = next((r["id"] for r in results if r.get("demo")), None) or (results[0]["id"] if results else None)
    if not demo:
        pytest.skip("the sandbox token sees no demo model")
    return demo


def test_core_and_pi_queries_validate(sandbox):
    async def go() -> dict:
        async with httpx.AsyncClient(timeout=60) as client:
            model_id = await _demo_model_id(client)
            out = {"model_id": model_id}
            for tier, query in matterport.TIERS.items():
                out[tier] = await matterport.post_graphql(client, query, {"id": model_id})
            out["search"] = await matterport.post_graphql(client, scan_identity.SEARCH_QUERY, {"q": '"1 Main"'})
            ids = f"query TurnkeyScanIdentities {{ m0: model(id: \"{model_id}\") {{{matterport.IDENTITY_FIELDS}\n}} }}"
            out["identity"] = await matterport.post_graphql(client, ids)
            return out

    res = asyncio.run(go())
    for part in ("core", "pi", "search", "identity"):
        assert not _validation_errors(res[part]), f"{part} query no longer validates: {_validation_errors(res[part])}"
    core = (res["core"].get("data") or {}).get("model")
    assert core and core.get("id") == res["model_id"], res["core"].get("errors")
    s = matterport.summarize({"model_id": res["model_id"], "core": core, "insights": (res["pi"].get("data") or {}).get("model")})
    assert set(matterport.interior_facts(s)) >= {"indoor_area_sqft", "ceiling", "rooms_by_type", "doorways", "tiers_available"}
