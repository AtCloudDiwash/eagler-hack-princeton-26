"""Step 2: find candidate buildings for the user's purpose (no agents yet).

Vexcel has no listings or text search, so discovery = geocode the place -> pull Vexcel parcels around
it (/property/extract) -> keep building types that suit the business -> deterministic pre-screen by
size and condition. Outside the key's geofence we fall back to OpenStreetMap building footprints and
say so. CoStar listings are not connected in this build (noted in the response).
"""
from __future__ import annotations

import uuid

import httpx

import db
from config import business, settings
from schemas import Candidate, Intent, SearchResponse
from services import external, vexcel, visual
from services.geo import centroid, haversine_m, in_coverage, property_id
from services.intent import parse, target_sqft

SEARCH_BOX_M = 1600
DEMO_CENTER = (29.7560, -95.3650)


def prescreen(c: dict, intent: Intent) -> tuple[int, list[str]]:
    """Deterministic 0-100 pre-screen (type 35, size 35, roof 20, data 10). Not the agent analysis."""
    cfg = business(intent.business_type)
    target, _ = target_sqft(intent)
    score, reasons = 0, []
    btype = c.get("building_type")
    if btype in cfg["suitable_building_types"]:
        score += 35
        reasons.append(f"{btype.replace('_', ' ').title()} building suits a {cfg['label'].lower()}")
    elif btype in cfg.get("acceptable_building_types", []):
        score += 15
        reasons.append(f"{btype.replace('_', ' ')} building: possible ground-floor commercial, verify")
    elif btype:
        reasons.append(f"{btype.replace('_', ' ')} building is an unusual fit")

    area = c.get("area_sqft")
    if area:
        ratio = area / target
        if 0.85 <= ratio <= 3:
            score += 35
            reasons.append(f"{area:,.0f} sq ft footprint fits ~{target:,} sq ft need")
        elif ratio > 3:
            score += 22
            reasons.append(f"Large {area:,.0f} sq ft building: would lease a suite")
        else:
            score += round(35 * max(0.0, ratio - 0.4) / 0.45)
            reasons.append(f"{area:,.0f} sq ft may be small for ~{target:,} sq ft")
    cond = c.get("roof_condition")
    if isinstance(cond, (int, float)):
        score += round(20 * (cond - 1) / 4)
        if cond >= 4:
            reasons.append(f"Roof in {c.get('roof_condition_label', '').lower()} condition")
        elif cond <= 2:
            reasons.append(f"Roof condition {c.get('roof_condition_label', '').lower()} ({cond:g}/5)")
    filled = sum(1 for k in ("building_type", "area_sqft", "roof_condition", "stories_est") if c.get(k) is not None)
    score += round(10 * filled / 4)
    return min(score, 100), reasons


async def _osm_buildings(lat: float, lon: float) -> list[dict]:
    """Commercial building footprints from OpenStreetMap (used outside Vexcel coverage), cached 3 days."""
    key = f"osm_buildings:{lat:.4f},{lon:.4f}"
    if (hit := db.cache_get(key, 3 * 86400)) is not None:
        return hit
    out = await _fetch_osm_buildings(lat, lon)
    if out:
        db.cache_set(key, out)
    return out


async def _fetch_osm_buildings(lat: float, lon: float) -> list[dict]:
    q = (
        "[out:json][timeout:40];("
        f'way["building"~"^(commercial|retail|office|industrial|warehouse)$"](around:900,{lat},{lon});'
        f'way["building"]["shop"](around:900,{lat},{lon});'
        ");out geom 80;"
    )
    out = []
    for e in await external.overpass(q):
        ring = [[p["lon"], p["lat"]] for p in e.get("geometry", [])]
        if len(ring) < 4:
            continue
        geom = {"type": "Polygon", "coordinates": [ring]}
        c = centroid(geom)
        # Shoelace area in m² (local equirectangular approximation) -> sq ft
        import math

        k = 111_320 * math.cos(math.radians(c[0]))
        pts = [((x - c[1]) * k, (y - c[0]) * 110_540) for x, y in ring]
        area_m2 = abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2
        tags = e.get("tags", {})
        levels = tags.get("building:levels")
        out.append({
            "id": property_id(c[0], c[1], "osm"),
            "lat": c[0],
            "lon": c[1],
            "footprint": geom,
            "parcel": None,
            "building_type": "commercial" if tags.get("building") in {"commercial", "retail", "office"} or tags.get("shop") else tags.get("building"),
            "area_sqft": round(area_m2 * 10.7639),
            "roof_condition": None,
            "roof_condition_label": None,
            "stories_est": int(levels) if levels and levels.isdigit() else None,
            "source": "osm",
            "address": " ".join(x for x in [tags.get("addr:housenumber"), tags.get("addr:street")] if x) or tags.get("name"),
        })
    return out


async def search(query: str) -> SearchResponse:
    intent = await parse(query)
    notes: list[str] = []
    location_text = intent.location_text
    if not location_text:
        location_text = "Houston, TX"
        notes.append("No location in the query, so the search defaults to Houston, TX (inside Vexcel coverage).")
    place = await external.geocode(location_text)
    if not place:
        return SearchResponse(intent=intent, location=None, data_mode="osm_only", candidates=[], notes=[f"Could not find “{location_text}”. Try adding the state."])
    lat, lon = place["lat"], place["lon"]
    covered = in_coverage(lat, lon)
    location = {"name": place["name"], "lat": lat, "lon": lon, "coverage": covered}

    raws: dict[str, dict | None] = {}
    candidates: list[dict] = []
    data_mode = "osm_only"
    if settings.vexcel_api_key and covered:
        try:
            features = await vexcel.property_extract(lat, lon, SEARCH_BOX_M, limit=300, calculated=True)
            data_mode = "vexcel_live"
            for f in features:
                c = vexcel.summarize_feature(f)
                candidates.append(c)
                raws[c["id"]] = f
        except vexcel.VexcelError as err:
            notes.append(f"Vexcel returned {err.status} ({err.message}); using OpenStreetMap footprints instead.")
    elif not settings.vexcel_api_key and haversine_m(lat, lon, *DEMO_CENTER) < 6000:
        data_mode = "vexcel_demo"
        notes.append("DEMO MODE: no VEXCEL_API_KEY set, showing a recorded Vexcel sample of downtown Houston.")
        try:
            for f in await vexcel.property_extract(lat, lon, SEARCH_BOX_M, limit=300):
                c = vexcel.summarize_feature(f, source="demo")
                candidates.append(c)
                raws[c["id"]] = f
        except vexcel.VexcelError as err:
            data_mode = "osm_only"
            notes.append(err.message)
    elif not covered:
        notes.append(f"{place['name']} is outside the Vexcel key's coverage (Los Angeles and Houston only). Building footprints come from OpenStreetMap, without Vexcel roof or site data.")

    if data_mode == "osm_only":
        try:
            candidates = await _osm_buildings(lat, lon)
        except (httpx.HTTPError, ValueError, RuntimeError) as err:
            notes.append(f"OpenStreetMap buildings unavailable right now ({str(err)[:80]}). Try again in a minute.")
            candidates = []

    if data_mode != "osm_only":
        # Warm OpenStreetMap places for the whole search area (box half-diagonal + 1.5 km catchment).
        external.prefetch_places(lat, lon, radius_m=external.PLACES_RADIUS_M + int(SEARCH_BOX_M * 0.72))
    cfg = business(intent.business_type)
    allowed = set(cfg["suitable_building_types"]) | set(cfg.get("acceptable_building_types", []))
    eligible: list[dict] = []
    seen_ids: set[str] = set()
    for c in candidates:
        if c["id"] in seen_ids:
            continue  # stacked parcels (condos, multi-structure lots) can share a centroid
        seen_ids.add(c["id"])
        if c.get("building_type") and c["building_type"] not in allowed:
            continue
        if c.get("_too_low"):
            continue  # roof under 8 ft: canopy/kiosk/shed rather than a leasable building
        c["match_score"], c["match_reasons"] = prescreen(c, intent)
        eligible.append(c)
    if data_mode != "osm_only":
        # Visual needs ("outdoor patio", "parking lot"...) re-rank by similarity in Vexcel imagery.
        note = await visual.apply(eligible, intent, lat, lon, SEARCH_BOX_M)
        if note:
            notes.append(note)
    scored = [Candidate(**c) for c in eligible]
    scored.sort(key=lambda c: (-c.match_score, haversine_m(lat, lon, c.lat, c.lon)))
    top = scored[:25]
    for c in top:
        db.save_property(c.model_dump(), raws.get(c.id))
    notes.append("Listings/asking rents (CoStar) are not connected; candidates are existing buildings that suit the use, not confirmed vacancies.")
    search_id = uuid.uuid4().hex[:12]
    db.save_search(search_id, query, intent.model_dump(), location, data_mode, [c.id for c in top])
    return SearchResponse(intent=intent, location=location, data_mode=data_mode, candidates=top, notes=notes, search_id=search_id)
