"""Turnkey Matchmaker API (FastAPI). Run: uvicorn main:app --reload --port 8000"""
from __future__ import annotations

import asyncio
import base64
import logging
import uuid

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

import db
import multi_agent_engine
from config import business_types, settings
from schemas import AnalysisRequest, MatterportLinkRequest, RefineRequest, RefineResponse, SearchRequest, SearchResponse
from services import costar, discovery, external, matterport, neighborhood, vexcel
from services.llm import llm_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("turnkey.api")
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
    return {"llm": await llm_status(), "vexcel": vexcel.mode(), "census": bool(settings.census_api_key), "matterport": matterport.has_credentials()}


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


def _detail(prop: dict, raw: dict | None, intent=None) -> dict:
    """Property detail. With the user's request (`intent`), the panel tiles describe what this building offers that
    request (services/fit_summary.py); without it, the building's recorded facts."""
    p = costar.match(prop["lat"], prop["lon"], prop.get("footprint"))
    shown = costar.reconcile(prop, p)  # CoStar's recorded stories / floor area / lot win over aerial estimates
    facts = vexcel.key_facts(raw)
    if p:
        recorded = {"Estimated stories": (p.get("stories"), "", "Recorded by CoStar"), "Est. total floor area": (p.get("gross_sqft"), " sq ft", "CoStar gross building area"),
                    "Lot (parcel) area": (p.get("lot_sqft"), " sq ft", "Recorded by CoStar")}
        for f in facts:
            value, unit, note = recorded.get(f["label"], (None, "", ""))
            if value:
                f["note"] = f"{note} (aerial estimate: {f['value']})"
                f["value"] = f"{value:,.0f}{unit}"
    from services import building_facts, fit_summary

    tiles = fit_summary.tiles(shown, raw, intent) if intent else building_facts.highlights(shown, raw)
    return {**shown, "key_facts": facts, "highlights": tiles, "raw": raw, "imagery": vexcel.imagery_meta(raw), "matterport": matterport.link_info(shown),
            "costar": costar.summarize(p) if p else None}


async def _replace_amenity_scan(prop: dict, raw: dict | None) -> dict:
    """A building whose auto-linked scan is an amenity (lobby, fitness center) or an apartment-unit tour gets a one-time
    search for a scan of an actual suite in the building; if none is found that tour is unlinked. User-linked tours are kept."""
    from services import scan_identity

    if prop.get("matterport_lookup_done") or prop.get("matterport_user_linked") or prop.get("matterport_user_unlinked"):
        return prop
    p = costar.match(prop["lat"], prop["lon"], prop.get("footprint"))
    scans = {s["id"]: s.get("caption") for s in (p or {}).get("matterport_scans") or [] if isinstance(s, dict) and s.get("id")}
    linked = prop.get("matterport_model_id")
    auto = linked and (prop.get("matterport_auto_model_id") == linked or (linked in scans and not prop.get("matterport_auto_model_id")))
    amenity_ids = [sid for sid, cap in scans.items() if scan_identity.not_the_space(cap)]  # amenities and apartment units
    if not ((auto and linked in amenity_ids) or (not linked and amenity_ids and len(amenity_ids) == len(scans))):
        return prop
    out = {**prop, "matterport_lookup_done": True}
    probe = linked or amenity_ids[0]
    found = None
    if matterport.has_credentials():
        try:
            r = await asyncio.wait_for(scan_identity.choose_scan({**prop, "matterport_model_id": probe}), timeout=12)
            if r.get("switched") and r.get("verdict") in ("verified", "likely"):
                found = r
        except Exception as err:  # noqa: BLE001 - the panel must open regardless
            # A failed or timed-out lookup is not "nothing found": leave the building as it is and retry next time.
            log.warning("scan lookup failed for %s (will retry): %s", prop.get("id"), err)
            return prop
    if found:
        out.update(matterport_model_id=found["model_id"], matterport_auto_model_id=found["model_id"],
                   matterport_note=f"Auto-linked '{found.get('name')}': {found['reason'].split(' The linked scan')[0]}")
    elif auto:
        out.update(matterport_model_id=None, matterport_auto_model_id=None, matterport_note=None)
    db.save_property(out, raw)
    return out


@app.post("/api/search/refine", response_model=RefineResponse)
async def refine_search(req: RefineRequest) -> RefineResponse:
    """Apply a follow-up to the current search (and re-run it), or answer a question about the current matches."""
    from services import refine

    if not req.message.strip():
        raise HTTPException(400, "Message is empty")
    out = await refine.refine(req.intent, req.message.strip(), req.history, req.matches)
    result = await discovery.search(req.message, intent=out["intent"]) if out["action"] == "refine" else None
    return RefineResponse(action=out["action"], reply=out["reply"], changes=out["changes"], result=result)


@app.get("/api/properties/{prop_id}")
async def property_detail(prop_id: str, business_type: str | None = None, sqft: int | None = Query(None, ge=100, le=1_000_000),
                          budget_amount: float | None = None, budget_period: str | None = None) -> dict:
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
    from services.fit_summary import intent_from_params

    intent = intent_from_params(business_type, sqft, budget_amount, budget_period)
    prop, tours_view = await _suite_tours(prop, raw, intent)
    if not (tours_view and tours_view["match"]):
        prop = await _replace_amenity_scan(prop, raw)
        if tours_view:
            tours_view = {**tours_view, "tours": [{**t, "linked": t["id"] == prop.get("matterport_model_id")} for t in tours_view["tours"]]}
    detail = _detail(prop, raw, intent)
    detail["matterport_tours"] = tours_view
    return detail


async def _suite_tours(prop: dict, raw: dict | None, intent, autolink: bool = True) -> tuple[dict, dict | None]:
    """The building's 3D tours, fetched live and labelled against the suite the user would lease. When a tour of that
    suite exists and the current tour was auto-linked (not the user's choice), link the suite's tour instead."""
    from services import program as space_program
    from services import suite_tours

    rec = costar.match(prop["lat"], prop["lon"], prop.get("footprint"))
    space = prop.get("best_space")
    if intent and rec:  # the suite chosen for THIS request
        prog = space_program.build(intent)
        size = prog["size"]
        space = costar.candidate_fields(rec, size["min_sqft"], size["max_sqft"], size["target_sqft"], prog["building"]["ground_floor"] == "required").get("best_space") or space
    try:
        tours = await asyncio.wait_for(suite_tours.building_tours(prop, rec), timeout=12)
    except asyncio.TimeoutError:
        return prop, None
    view = suite_tours.for_property(tours, space, prop.get("matterport_model_id"))
    m, linked = view["match"], prop.get("matterport_model_id")
    auto = prop.get("matterport_auto_model_id")
    # The user's own choice (pasted, or picked from the tour list) is never replaced: a link that differs from the
    # auto-linked id, or (older records without an auto id) one that isn't among the building's known tours.
    user_linked = prop.get("matterport_user_linked") or (bool(linked) and (auto != linked if auto else linked not in {t["id"] for t in tours}))
    if autolink and not prop.get("matterport_user_unlinked") and m and m["confidence"] == "strong" and linked != m["id"] and not user_linked:
        t = next(x for x in tours if x["id"] == m["id"])
        prop = {**prop, "matterport_model_id": m["id"], "matterport_auto_model_id": m["id"], "matterport_lookup_done": True,
                "matterport_note": f"Tour of Suite {view['suite']} ('{t['name']}')" + (f"; {'; '.join(m['caveats'])}." if m["caveats"] else ".")}
        db.save_property(prop, raw)
        view = suite_tours.for_property(tours, space, m["id"])
    return prop, view


@app.get("/api/properties/{prop_id}/neighborhood")
async def property_neighborhood(prop_id: str, radius_m: int = Query(400, ge=100, le=1500)) -> dict:
    stored = db.get_property(prop_id)
    if not stored:
        raise HTTPException(404, "Unknown property")
    prop, _ = stored
    return await neighborhood.build(prop["lat"], prop["lon"], radius_m, exclude_id=prop_id)


@app.put("/api/properties/{prop_id}/matterport")
async def link_matterport(prop_id: str, req: MatterportLinkRequest) -> dict:
    """Link a Matterport tour (showcase URL or model id) to a building. Interior data is fetched now when
    reachable, so a bad link or token shows up here instead of during the analysis."""
    model_id = matterport.parse_model_id(req.tour)
    if not model_id:
        raise HTTPException(400, "Not a Matterport tour link. Paste a URL like https://my.matterport.com/show/?m=SxQL3iGyoDo or the 11-character model id.")
    stored = db.set_matterport_model(prop_id, model_id)
    if not stored:
        raise HTTPException(404, "Unknown property")
    prop, raw = stored
    prop = {**prop, "matterport_user_linked": True, "matterport_auto_model_id": None}
    prop.pop("matterport_user_unlinked", None)
    db.save_property(prop, raw)
    prop, tours_view = await _suite_tours(prop, raw, None, autolink=False)
    detail = _detail(prop, raw)
    detail["matterport_tours"] = tours_view
    if matterport.data_mode(model_id) != "embed_only":
        try:
            scan = matterport.summarize(await asyncio.wait_for(matterport.fetch_model(model_id), timeout=30))
            detail["matterport"]["scan"] = {"name": scan["name"], "floors": len(scan["floors"]), "rooms": len(scan["rooms"]), "total_indoor_area_sqft": scan["total_indoor_area_sqft"], "insights_available": scan["insights_available"]}
        except Exception as err:  # noqa: BLE001 - keep the link; the tour is still viewable
            detail["matterport"]["note"] = f"Tour linked, but interior data could not be loaded: {err}"
    return detail


@app.delete("/api/properties/{prop_id}/matterport")
async def unlink_matterport(prop_id: str) -> dict:
    stored = db.set_matterport_model(prop_id, None)
    if not stored:
        raise HTTPException(404, "Unknown property")
    prop, raw = stored
    prop = {**prop, "matterport_user_unlinked": True, "matterport_lookup_done": True}  # never auto-link a tour again here
    db.save_property(prop, raw)
    prop, tours_view = await _suite_tours(prop, raw, None, autolink=False)
    detail = _detail(prop, raw)
    detail["matterport_tours"] = tours_view
    return detail


@app.post("/api/analyses")
async def start_analysis(req: AnalysisRequest) -> dict:
    stored = db.get_property(req.property_id)
    if not stored:
        raise HTTPException(404, "Unknown property")
    analysis_id = uuid.uuid4().hex[:12]
    db.create_analysis(analysis_id, req.query, req.intent.model_dump(), _detail(*stored), req.radius_m)
    task = asyncio.create_task(multi_agent_engine.run_analysis(analysis_id, req))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return {"id": analysis_id, "status": "queued"}


@app.get("/api/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    a = db.get_analysis(analysis_id)
    if not a:
        raise HTTPException(404, "Unknown analysis")
    return a


@app.get("/api/analyses")
def list_analyses() -> list[dict]:
    out = []
    for a in db.list_analyses():
        rec = (a.get("result") or {}).get("recommendation") or {}
        p = a["property"]
        out.append({
            "id": a["id"], "status": a["status"], "created_at": a["created_at"], "query": a["query"],
            "business_label": a["intent"].get("business_label"),
            "property": {"id": p.get("id"), "lat": p.get("lat"), "lon": p.get("lon"), "building_type": p.get("building_type"), "area_sqft": p.get("area_sqft"), "address": p.get("address")},
            "score": rec.get("score"), "confidence": rec.get("confidence"), "verdict": rec.get("verdict"),
        })
    return out
