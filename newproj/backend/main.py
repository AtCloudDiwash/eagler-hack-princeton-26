"""Turnkey Matchmaker API (FastAPI). Run: uvicorn main:app --reload --port 8000"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import uuid

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

import db
import multi_agent_engine
from config import business_types, settings
from schemas import AnalysisRequest, SearchRequest, SearchResponse
from services import discovery, external, neighborhood, vexcel
from services.llm import llm_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = FastAPI(title="Turnkey Matchmaker", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])
_running: set[asyncio.Task] = set()
_TRANSPARENT_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


@app.on_event("startup")
def startup() -> None:
    db.conn()
    db.mark_interrupted()


@app.get("/api/health")
async def health() -> dict:
    return {"llm": await llm_status(), "vexcel": vexcel.mode(), "census": bool(settings.census_api_key), "matterport": bool(settings.matterport_api_key)}


@app.get("/api/business-types")
def list_business_types() -> list[dict]:
    return [{"id": k, "label": v["label"], "icon": v.get("icon", ""), "default_radius_m": v["default_radius_m"]} for k, v in business_types().items()]


@app.get("/api/tiles/{z}/{x}/{y}")
async def tiles(z: int, x: int, y: int) -> Response:
    data = await vexcel.tile(z, x, y)
    if data is None:
        # Transparent PNG (not 204) so map libraries render nothing instead of logging image errors.
        return Response(content=_TRANSPARENT_PNG, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    if not req.query.strip():
        raise HTTPException(400, "Query is empty")
    return await discovery.search(req.query)


def _detail(prop: dict, raw: dict | None) -> dict:
    return {**prop, "key_facts": vexcel.key_facts(raw), "raw": raw, "imagery": vexcel.imagery_meta(raw)}


@app.get("/api/properties/{prop_id}")
async def property_detail(prop_id: str) -> dict:
    stored = db.get_property(prop_id)
    if not stored:
        raise HTTPException(404, "Unknown property (run a search first)")
    prop, raw = stored
    external.prefetch_places(prop["lat"], prop["lon"])  # warm the slow Overpass fetch for the neighborhood view
    if not prop.get("address"):
        rev = await external.reverse(prop["lat"], prop["lon"])
        if rev.get("address"):
            prop["address"] = rev["address"]
            db.save_property(prop, raw)
    return _detail(prop, raw)


@app.get("/api/properties/{prop_id}/neighborhood")
async def property_neighborhood(prop_id: str, radius_m: int = Query(400, ge=100, le=1500)) -> dict:
    stored = db.get_property(prop_id)
    if not stored:
        raise HTTPException(404, "Unknown property")
    prop, _ = stored
    return await neighborhood.build(prop["lat"], prop["lon"], radius_m, exclude_id=prop_id)


@app.post("/api/analyses")
async def start_analysis(req: AnalysisRequest) -> dict:
    stored = db.get_property(req.property_id)
    if not stored:
        raise HTTPException(404, "Unknown property")
    analysis_id = uuid.uuid4().hex[:12]
    db.create_analysis(analysis_id, req.query, req.intent.model_dump(), _detail(*stored), req.radius_m, req.mode, req.search_id, req.requirements)
    task = asyncio.create_task(multi_agent_engine.run_analysis(analysis_id, req))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return {"id": analysis_id, "status": "queued"}


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "Unknown analysis")
    return {**a, "search_id": _group_key(a)}


def _group_key(a: dict) -> str:
    """Which search an analysis belongs to. Analyses made before search ids are grouped by request + business."""
    if a.get("search_id"):
        return a["search_id"]
    basis = f"{(a.get('base_query') or a['query']).strip().lower()}|{a['intent'].get('business_type')}"
    return "legacy-" + hashlib.sha1(basis.encode()).hexdigest()[:10]


def _summary(a: dict) -> dict:
    rec = (a.get("result") or {}).get("recommendation") or {}
    p = a["property"]
    costs = (a.get("result") or {}).get("costs") or {}
    return {
        "id": a["id"], "status": a["status"], "created_at": a["created_at"], "query": a["query"],
        "base_query": a.get("base_query") or a["query"], "extra_requirements": a.get("extra_requirements"),
        "business_type": a["intent"].get("business_type"), "business_label": a["intent"].get("business_label"),
        "property": {"id": p.get("id"), "lat": p.get("lat"), "lon": p.get("lon"), "building_type": p.get("building_type"), "area_sqft": p.get("area_sqft"), "address": p.get("address")},
        "score": rec.get("score"), "confidence": rec.get("confidence"), "verdict": rec.get("verdict"), "mode": a.get("mode", "deep"),
        "search_id": _group_key(a), "budget_status": (costs.get("budget") or {}).get("status"),
    }


@app.get("/api/analyses")
def list_analyses() -> list[dict]:
    return [_summary(a) for a in db.list_analyses()]


@app.get("/api/searches/{search_id}")
def get_search(search_id: str) -> dict:
    """One search: its request, its ranked candidate buildings and the analyses run on them (for Compare)."""
    analyses = [a for a in db.list_analyses() if _group_key(a) == search_id]
    search = db.get_search(search_id)
    if not search and not analyses:
        raise HTTPException(404, "Unknown search")
    if search:
        candidates = [c for c, _ in filter(None, (db.get_property(pid) for pid in search["candidate_ids"]))]
        query, intent, location = search["query"], search["intent"], search["location"]
    else:  # legacy group: no stored candidate list, only the analyzed buildings
        first = analyses[-1]
        candidates = [a["property"] for a in analyses]
        query, intent, location = first.get("base_query") or first["query"], first["intent"], None
    return {
        "id": search_id, "query": query, "intent": intent, "location": location, "legacy": search is None,
        "candidates": [{k: c.get(k) for k in ("id", "lat", "lon", "building_type", "area_sqft", "roof_condition", "roof_condition_label", "stories_est", "match_score", "match_reasons", "address", "source")} for c in candidates],
        "analyses": [_summary(a) for a in analyses],
    }
