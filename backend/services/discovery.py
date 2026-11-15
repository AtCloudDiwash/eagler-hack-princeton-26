"""Step 2: find candidate buildings for the user's purpose (no agents yet).

Vexcel has no listings or text search, so discovery = geocode the place -> pull Vexcel parcels around
it (/property/extract) -> keep building types that suit the business -> deterministic pre-screen by
size and condition. Outside the key's geofence we fall back to OpenStreetMap building footprints and
say so. CoStar listings are not connected in this build (noted in the response).
"""
from __future__ import annotations

import asyncio
import re

import httpx

import db
from config import business, settings
from schemas import Candidate, Intent, SearchResponse
from services import costar, external, program as space_program, vexcel
from services.geo import centroid, haversine_m, in_coverage, property_id
from services.intent import parse, target_sqft

SEARCH_BOX_M = 1600
OSM_DEADLINE_S = 45
DEMO_CENTER = (29.7560, -95.3650)


def prescreen(c: dict, intent: Intent, program: dict | None = None, feature: dict | None = None) -> tuple[int, list[str]]:
    """Deterministic 0-100 pre-screen (type 35, size 35, roof 20, data 10, minus program conflicts on
    must-haves). Not the agent analysis."""
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
    best = c.get("best_space")
    if best:  # CoStar lists a suite in the user's size range: the strongest size evidence there is
        score += 35
        rent = f" at ${best['rent_per_sqft_yr']:.2f}/sq ft/yr" if best.get("rent_per_sqft_yr") else ""
        floor = f", {best['floor'].lower()}" if best.get("floor") else ""
        reasons.insert(0, f"On the market (CoStar): {('Suite ' + str(best['suite'])) if best.get('suite') else 'a space'} with {best['sqft']:,.0f} rentable sq ft{floor}{rent}")
        if best.get("ground_floor") is False and cfg["program"]["ground_floor"] == "required":
            score -= 25
            reasons.insert(1, f"Ground floor: that suite is on the {best['floor'].lower()}, but a {cfg['label'].lower()} needs street level")
        area = None  # size already scored from the listing
    elif c.get("space_count"):
        score += 12
        reasons.append(f"CoStar lists {c['space_count']} space(s) here ({c['available_sqft'] or 0:,.0f} sq ft), none in your ~{target:,} sq ft range")
        area = None
    if c.get("costar_type") == "Multifamily":
        # Vexcel may call it "commercial" (ground-floor retail), but CoStar records an apartment building.
        reasons[:] = [r for r in reasons if not r.lower().startswith(("commercial building", "retail building", "office building"))]
        if best and str(best.get("use") or "").lower() == "retail":
            reasons.insert(1, f"Ground-floor retail in an apartment building (CoStar: multifamily): the space for lease is the {best.get('floor', 'retail suite').lower()} shop space")
        else:
            reasons.insert(1 if best else 0, "Apartment building (CoStar: multifamily): confirm a commercial space exists and is allowed")
    if c.get("rentable_sqft") and not best:
        reasons.append(f"Rentable area (CoStar {c.get('rentable_basis') or 'RBA'}): {c['rentable_sqft']:,.0f} sq ft for the whole building")
    if area:
        ratio = area / target
        if 0.85 <= ratio <= 3:
            score += 35
            reasons.append(f"Building footprint {area:,.0f} sq ft can hold your ~{target:,} sq ft")
        elif ratio > 3:
            score += 22
            reasons.append(f"Large building ({area:,.0f} sq ft footprint): you would lease a suite")
        else:
            score += round(35 * max(0.0, ratio - 0.4) / 0.45)
            reasons.append(f"Building footprint {area:,.0f} sq ft may be small for ~{target:,} sq ft")
    cond = c.get("roof_condition")
    if isinstance(cond, (int, float)):
        score += round(20 * (cond - 1) / 4)
        if cond >= 4:
            reasons.append(f"Roof in {c.get('roof_condition_label', '').lower()} condition")
        elif cond <= 2:
            reasons.append(f"Roof condition {c.get('roof_condition_label', '').lower()} ({cond:g}/5)")
    filled = sum(1 for k in ("building_type", "area_sqft", "roof_condition", "stories_est") if c.get(k) is not None)
    score += round(10 * filled / 4)
    if program:
        # what the user's program needs from the building (ground floor, ceiling, paving for parking/drive-thru...)
        must = {n["id"] for n in program["needs"] if n["priority"] == "must"} | ({"ground_floor"} if program["building"]["ground_floor"] == "required" else set())
        for chk in space_program.site_checks(program, space_program.facts_from(c, feature)):
            if chk["id"] in {"size", "timeline", "sprinklers", "exits"}:
                continue  # size scored above; the rest are not building-specific at this stage
            if chk["status"] == "risk":
                score -= 10 if chk["id"] in must else 4
                reasons.append(f"{chk['label']}: {chk['detail']}")
            elif chk["status"] == "pass" and chk["id"] in must | {"ceiling"}:
                reasons.append(f"{chk['label']}: {chk['detail']}")
    return max(0, min(score, 100)), reasons


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


_US_STATES = (
    "alabama al alaska ak arizona az arkansas ar california ca colorado co connecticut ct delaware de florida fl georgia ga "
    "hawaii hi idaho id illinois il indiana in iowa ia kansas ks kentucky ky louisiana la maine me maryland md massachusetts ma "
    "michigan mi minnesota mn mississippi ms missouri mo montana mt nebraska ne nevada nv ohio oh oklahoma ok oregon or "
    "pennsylvania pa tennessee tn texas tx utah ut vermont vt virginia va washington wa wisconsin wi wyoming wy"
).split() + ["new hampshire", "nh", "new jersey", "nj", "new mexico", "nm", "new york", "ny", "north carolina", "nc", "north dakota", "nd", "rhode island", "ri", "south carolina", "sc", "south dakota", "sd", "west virginia", "wv", "dc"]
_CITY_TYPES = {"city", "town", "village", "municipality", "state"}


def _names_state(text: str) -> bool:
    t = re.sub(r"[^a-z ,]", " ", text.lower())
    parts = [p.strip() for p in t.split(",")]
    return len(parts) > 1 and parts[-1] in _US_STATES or any(re.search(rf"\b{s}\b", t) for s in _US_STATES if len(s) > 2)


async def locate(text: str, notes: list[str]) -> dict | None:
    """Geocode the user's place. A bare neighborhood name ("Montrose", "the Heights") often matches a
    same-named county or town elsewhere in the US; when the match is outside Vexcel coverage, isn't a city,
    and no state was given, try the name inside the covered cities and use that instead (with a note)."""
    place = await external.geocode(text)
    if place and in_coverage(place["lat"], place["lon"]):
        return place
    if _names_state(text) or (place and place.get("addresstype") in _CITY_TYPES):
        return place  # the user named a state, or a real city outside coverage: respect it
    for city in ("Houston, TX", "Los Angeles, CA"):
        alt = await external.geocode(f"{text}, {city}")
        if alt and in_coverage(alt["lat"], alt["lon"]):
            where = f" (not {place['display_name']})" if place else ""
            notes.append(f"Read “{text}” as {alt['name']}, {city}{where}. Add the city or state to search somewhere else.")
            return alt
    return place


def attach_costar(candidates: list[dict], lat: float, lon: float, cfg: dict, prog: dict, notes: list[str]) -> set[int]:
    """Give every building its CoStar record (rentable area, spaces on the market, asking rents) and add the
    CoStar-listed properties for this use that the building search missed. Returns the listed CoStar ids."""
    if not costar.available():
        return set()
    size = prog["size"]
    ground = prog["building"]["ground_floor"] == "required"
    matched: set[int] = set()
    for c in candidates:
        p = costar.match(c["lat"], c["lon"], c.get("footprint"))
        if p and p["id"] not in matched:
            matched.add(p["id"])
            c.update(costar.candidate_fields(p, size["min_sqft"], size["max_sqft"], size["target_sqft"], ground))
            c.update(costar.reconcile(c, p))
            c["address"] = c.get("address") or p.get("address")
    types = cfg.get("costar_property_types", [])
    listed = costar.listed_near(lat, lon, SEARCH_BOX_M / 2, types)
    added = 0
    for p in listed:
        if p["id"] in matched:
            continue
        c = {"id": property_id(p["lat"], p["lon"], prefix="cs"), "lat": p["lat"], "lon": p["lon"], "footprint": None, "parcel": None,
             "building_type": "commercial", "area_sqft": None, "roof_condition": None, "roof_condition_label": None,
             "stories_est": p.get("stories"), "source": "costar", "address": p.get("address")}
        c.update(costar.candidate_fields(p, size["min_sqft"], size["max_sqft"], size["target_sqft"], ground))
        c.update(costar.reconcile(c, p))
        candidates.append(c)
        added += 1
    n_listed = sum(1 for c in candidates if c.get("space_count"))
    if n_listed:
        notes.append(f"{n_listed} building(s) here have spaces on the market in CoStar" + (f" ({added} not in the aerial building search, shown from CoStar)" if added else "") + ". Their rentable sq ft and asking rents come from the CoStar kit snapshot.")
    return {p["id"] for p in listed}


async def search(query: str) -> SearchResponse:
    intent = await parse(query)
    notes: list[str] = []
    location_text = intent.location_text
    if not location_text:
        location_text = "Houston, TX"
        notes.append("No location in the query, so the search defaults to Houston, TX (inside Vexcel coverage).")
    place = await locate(location_text, notes)
    if not place:
        return SearchResponse(intent=intent, location=None, data_mode="osm_only", candidates=[], notes=[f"Could not find “{location_text}”. Try adding the state."], program=space_program.build(intent))
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
            # Overpass retries across endpoints can take minutes when it is overloaded; don't hang the search.
            candidates = await asyncio.wait_for(_osm_buildings(lat, lon), timeout=OSM_DEADLINE_S)
        except asyncio.TimeoutError:
            notes.append(f"OpenStreetMap didn't answer within {OSM_DEADLINE_S}s, so no buildings could be listed here. Try again in a minute, or search in Houston or Los Angeles (Vexcel coverage).")
            candidates = []
        except (httpx.HTTPError, ValueError, RuntimeError) as err:
            notes.append(f"OpenStreetMap buildings unavailable right now ({str(err)[:80]}). Try again in a minute.")
            candidates = []

    if data_mode != "osm_only":
        # Warm OpenStreetMap places for the whole search area (box half-diagonal + 1.5 km catchment).
        external.prefetch_places(lat, lon, radius_m=external.PLACES_RADIUS_M + int(SEARCH_BOX_M * 0.72))
    cfg = business(intent.business_type)
    prog = space_program.build(intent)
    allowed = set(cfg["suitable_building_types"]) | set(cfg.get("acceptable_building_types", []))
    listed = attach_costar(candidates, lat, lon, cfg, prog, notes)
    scored: list[Candidate] = []
    seen_ids: set[str] = set()
    for c in candidates:
        if c["id"] in seen_ids:
            continue  # stacked parcels (condos, multi-structure lots) can share a centroid
        seen_ids.add(c["id"])
        if c.get("building_type") and c["building_type"] not in allowed and c.get("costar_id") not in listed:
            continue  # a CoStar lease listing for this use outranks Vexcel's building class
        if c.get("_too_low"):
            continue  # roof under 8 ft: canopy/kiosk/shed rather than a leasable building
        c["match_score"], c["match_reasons"] = prescreen(c, intent, prog, raws.get(c["id"]))
        scored.append(Candidate(**c))
    # A space actually on the market in the user's size range beats any building that merely could suit;
    # then by fit score. Keep some other listed buildings in the list too (spaces can often be combined/divided).
    scored.sort(key=lambda c: (c.best_space is None, -c.match_score, haversine_m(lat, lon, c.lat, c.lon)))
    top = scored[:25]
    extra_listed = [c for c in scored[25:] if c.space_count][: max(0, 8 - sum(1 for c in top if c.space_count))]
    if extra_listed:
        top = top[: 25 - len(extra_listed)] + extra_listed
    from services.scan_identity import default_scan  # no network: picks among CoStar's scans by caption only

    for c in top:
        row = c.model_dump()
        auto_scan = default_scan(costar.match(c.lat, c.lon, c.footprint)) if c.costar_id else None
        stored = db.get_property(c.id)
        if auto_scan and not (stored and "matterport_model_id" in stored[0]):
            # CoStar's own 3D scan of this property (user can change or unlink it). The auto id is remembered so
            # the Matterport Agent can tell an auto link (may be replaced by a better scan) from a user's choice.
            row["matterport_model_id"] = row["matterport_auto_model_id"] = auto_scan
        elif stored and stored[0].get("matterport_auto_model_id"):
            row["matterport_auto_model_id"] = stored[0]["matterport_auto_model_id"]
        db.save_property(row, raws.get(c.id))
    if not costar.available():
        notes.append("CoStar data isn't loaded (run scripts/build_costar_index.py), so rentable area and spaces on the market are unknown; candidates are existing buildings, not confirmed vacancies.")
    elif not any(c.space_count for c in top):
        notes.append("No CoStar-listed spaces in this area for this use; candidates are existing buildings that suit the use, not confirmed vacancies.")
    return SearchResponse(intent=intent, location=location, data_mode=data_mode, candidates=top, notes=notes, program=prog)
