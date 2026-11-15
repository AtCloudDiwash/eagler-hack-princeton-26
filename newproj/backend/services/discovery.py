"""Step 2: find candidate buildings for the user's purpose (no agents yet).

Vexcel has no listings or text search, so discovery = geocode the place -> pull Vexcel parcels around
it (/property/extract) -> keep building types that suit the business -> deterministic pre-screen by
size and condition. Outside the key's geofence we fall back to OpenStreetMap building footprints and
say so. CoStar listings are not connected in this build (noted in the response).
"""
from __future__ import annotations

import asyncio
import json
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


def prescreen(c: dict, intent: Intent, center: tuple[float, float] | None = None) -> tuple[int, list[str]]:
    """Deterministic 0-100 pre-screen (type 30, size 30, closeness 15, roof 15, data 10). Not the agent analysis.
    Size is scored on a curve around the target (a near-exact fit beats "big enough"), and closeness to the place
    the user searched counts, so candidates don't all tie at ~95."""
    cfg = business(intent.business_type)
    target, _ = target_sqft(intent)
    score, reasons = 0.0, []
    btype = c.get("building_type")
    if btype in cfg["suitable_building_types"]:
        score += 30
        reasons.append(f"{btype.replace('_', ' ').title()} building suits a {cfg['label'].lower()}")
    elif btype in cfg.get("acceptable_building_types", []):
        score += 13
        reasons.append(f"{btype.replace('_', ' ')} building: possible ground-floor commercial, verify")
    elif btype:
        reasons.append(f"{btype.replace('_', ' ')} building is an unusual fit")

    area = c.get("area_sqft")
    if area:
        ratio = area / target
        if 1 <= ratio <= 2:
            score += 30
            reasons.append(f"{area:,.0f} sq ft footprint fits ~{target:,} sq ft need")
        elif 0.85 <= ratio < 1 or 2 < ratio <= 4:
            score += 25
            reasons.append(f"{area:,.0f} sq ft footprint for ~{target:,} sq ft need" + (": would lease part of it" if ratio > 2 else ""))
        elif ratio > 4:
            score += 18 if ratio <= 15 else 12
            reasons.append(f"Large {area:,.0f} sq ft building: would lease a suite")
        else:
            score += 30 * max(0.0, ratio - 0.4) / 0.6
            reasons.append(f"{area:,.0f} sq ft may be small for ~{target:,} sq ft")
    cond = c.get("roof_condition")
    if isinstance(cond, (int, float)):
        score += 15 * (cond - 1) / 4
        if cond >= 4:
            reasons.append(f"Roof in {c.get('roof_condition_label', '').lower()} condition")
        elif cond <= 2:
            reasons.append(f"Roof condition {c.get('roof_condition_label', '').lower()} ({cond:g}/5)")
    if center:
        d = haversine_m(center[0], center[1], c["lat"], c["lon"])
        score += 15 * max(0.0, 1 - d / 1200)
        if d <= 400:
            reasons.append(f"{d:,.0f} m from the place you searched")
    filled = sum(1 for k in ("building_type", "area_sqft", "roof_condition", "stories_est") if c.get(k) is not None)
    score += 10 * filled / 4
    return min(round(score), 100), reasons


INNER_BOX_M = 700


async def _vexcel_rings(lat: float, lon: float) -> list[dict]:
    """Parcels around the point, closest first. Vexcel caps each request (total-records) and does not return
    parcels nearest-first, so a single big box can miss the buildings next to the searched spot. An inner box
    guarantees the close ones; the full box adds the rest. Both run in parallel."""
    inner, outer = await asyncio.gather(
        vexcel.property_extract(lat, lon, INNER_BOX_M, limit=200, calculated=True),
        vexcel.property_extract(lat, lon, SEARCH_BOX_M, limit=300, calculated=True),
    )
    seen, merged = set(), []
    for f in [*inner, *outer]:
        fid = f.get("id") or json.dumps(f.get("geometry"), sort_keys=True)[:200]
        if fid not in seen:
            seen.add(fid)
            merged.append(f)
    c = lambda f: centroid(f.get("geometry")) or (90.0, 0.0)  # noqa: E731 - no geometry sorts last
    return sorted(merged, key=lambda f: haversine_m(lat, lon, *c(f)))


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
    try:
        place = await external.geocode(location_text)
    except httpx.HTTPError as err:
        return SearchResponse(intent=intent, location=None, data_mode="osm_only", candidates=[], notes=[f"The place lookup (OpenStreetMap) is unavailable right now ({type(err).__name__}). Try again in a few seconds."])
    if not place:
        return SearchResponse(intent=intent, location=None, data_mode="osm_only", candidates=[], notes=[f"Could not find “{location_text}”. Try adding the state."])
    lat, lon = place["lat"], place["lon"]
    covered = in_coverage(lat, lon)
    location = {"name": place["name"], "lat": lat, "lon": lon, "coverage": covered, "display_name": place.get("display_name")}
    if place.get("biased_to") or (place.get("display_name") and place["name"].lower() not in location_text.lower()):
        notes.append(f"“{location_text}” was matched to {', '.join((place.get('display_name') or place['name']).split(', ')[:3])}. Add the city if you meant somewhere else.")

    raws: dict[str, dict | None] = {}
    candidates: list[dict] = []
    data_mode = "osm_only"
    if settings.vexcel_api_key and covered:
        try:
            features = await _vexcel_rings(lat, lon)
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
        if (not c.get("lat") and not c.get("lon")) or (not c.get("building_type") and not c.get("area_sqft")):
            continue  # no structure (empty lot / parking) or no geometry
        if c.get("_too_low"):
            continue  # roof under 8 ft: canopy/kiosk/shed rather than a leasable building
        c["match_score"], c["match_reasons"] = prescreen(c, intent, (lat, lon))
        eligible.append(c)
    if data_mode != "osm_only":
        # Visual needs ("outdoor patio", "parking lot"...) re-rank by similarity in Vexcel imagery.
        note = await visual.apply(eligible, intent, lat, lon, SEARCH_BOX_M, query)
        if note:
            notes.append(note)
    scored = [Candidate(**c) for c in eligible]
    scored.sort(key=lambda c: (-c.match_score, haversine_m(lat, lon, c.lat, c.lon)))
    top = scored[:25]
    for c in top:
        db.save_property(c.model_dump(), raws.get(c.id))
    notes.append("Listings/asking rents (CoStar) are not connected; candidates are existing buildings that suit the use, not confirmed vacancies.")
    search_id = uuid.uuid4().hex[:12]
    db.save_search(search_id, query, intent.model_dump(), location, data_mode, [c.id for c in top],
                   {c.id: {"match_score": c.match_score, "match_reasons": c.match_reasons} for c in top})
    return SearchResponse(intent=intent, location=location, data_mode=data_mode, candidates=top, notes=notes, search_id=search_id)
