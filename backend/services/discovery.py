"""Step 2: find candidate buildings for the user's purpose (no agents yet).

Vexcel has no listings or text search, so discovery = geocode the place -> pull Vexcel parcels around
it (/property/extract) -> keep building types that suit the business -> deterministic pre-screen by
size and condition. Outside the key's geofence we fall back to OpenStreetMap building footprints and
say so. CoStar listings supply available suites, rentable areas and asking rents when the kit index is present.
"""
from __future__ import annotations

import asyncio
import re

import httpx

import db
from config import business, settings
from schemas import Candidate, Intent, SearchResponse
from services import costs, costar, external, program as space_program, sizing, vexcel
from services.geo import centroid, haversine_m, in_coverage, property_id
from services.intent import parse

# The search area: a box reaching SEARCH_RADIUS_M from the place, for both the Vexcel building sweep and CoStar
# listings. Widened to WIDE_RADIUS_M when fewer than MIN_SUITABLE buildings of a suitable type are inside it.
SEARCH_RADIUS_M = 800
WIDE_RADIUS_M = 1600
MIN_SUITABLE = 12
OSM_DEADLINE_S = 45
DEMO_CENTER = (29.7560, -95.3650)


# Pre-screen weights (sum 100). Size and distance are graded, so too big, too small and too far all score lower.
W_TYPE, W_SIZE, W_NEAR, W_ROOF, W_EVIDENCE = 25, 35, 15, 15, 10
NEAR_FULL_M, NEAR_ZERO_M = 250, 1600  # full distance points within 250 m of the searched place, none at 1.6 km


def proximity(distance_m: float | None) -> float | None:
    """1 within NEAR_FULL_M of the searched place, linear to 0 at NEAR_ZERO_M."""
    if distance_m is None:
        return None
    return max(0.0, min(1.0, (NEAR_ZERO_M - distance_m) / (NEAR_ZERO_M - NEAR_FULL_M)))


def _distance_text(d: float) -> str:
    return f"{d:,.0f} m" if d < 1000 else f"{d / 1000:.1f} km"


def prescreen(c: dict, intent: Intent, program: dict | None = None, feature: dict | None = None, place_name: str | None = None) -> tuple[int, list[str]]:
    """Deterministic 0-100 pre-screen: building type 25, size fit 35 (services/sizing.py), distance from the
    searched place 15, roof 15, evidence 10, minus program conflicts on must-haves. Not the agent analysis."""
    cfg = business(intent.business_type)
    size = (program or {}).get("size") or sizing.estimate(intent)
    ground_required = cfg["program"]["ground_floor"] == "required"
    score, reasons = 0.0, []
    btype = c.get("building_type")
    if btype in cfg["suitable_building_types"]:
        score += W_TYPE
        reasons.append(f"{btype.replace('_', ' ').title()} building suits a {cfg['label'].lower()}")
    elif btype in cfg.get("acceptable_building_types", []):
        score += W_TYPE * 0.4
        reasons.append(f"{btype.replace('_', ' ')} building: possible ground-floor commercial, verify")
    elif btype:
        reasons.append(f"{btype.replace('_', ' ')} building is an unusual fit")

    best = c.get("best_space")
    if best:  # A specific CoStar vacancy is stronger size evidence than the whole-building area
        rent = f" at ${best['rent_per_sqft_yr']:.2f}/sq ft/yr" if best.get("rent_per_sqft_yr") else ""
        floor = f", {best['floor'].lower()}" if best.get("floor") else ""
        sq = f"{best['sqft_min']:,.0f}-{best['sqft']:,.0f}" if best.get("sqft_min") else f"{best['sqft']:,.0f}"
        if best.get("suggested_portion"):
            sq = f"{best['sqft']:,.0f} proposed ({best['sqft_min']:,.0f}–{best['sqft_max']:,.0f} advertised; confirm division)"
        reasons.insert(0, f"On the market (CoStar): {('Suite ' + str(best['suite'])) if best.get('suite') else 'a space'} with {sq} rentable sq ft{floor}{rent}")
        if best.get("ground_floor") is False and ground_required:
            score -= 20
            reasons.insert(1, f"Ground floor: that suite is on the {best['floor'].lower()}, but a {cfg['label'].lower()} needs street level")
    if c.get("costar_type") == "Multifamily":
        # Vexcel may call it "commercial" (ground-floor retail), but CoStar records an apartment building.
        reasons[:] = [r for r in reasons if not r.lower().startswith(("commercial building", "retail building", "office building"))]
        if best and str(best.get("use") or "").lower() == "retail":
            reasons.insert(1, f"Ground-floor retail in an apartment building (CoStar: multifamily): the space for lease is the {best.get('floor', 'retail suite').lower()} shop space")
        else:
            reasons.insert(1 if best else 0, "Apartment building (CoStar: multifamily): confirm a commercial space exists and is allowed")
    if c.get("rentable_sqft") and not best:
        reasons.append(f"Rentable area (CoStar {c.get('rentable_basis') or 'RBA'}): {c['rentable_sqft']:,.0f} sq ft for the whole building")

    graded = sizing.fit(size, best_space=best, closest_space_sqft=c.get("closest_space_sqft"), space_count=c.get("space_count") or 0,
                        available_sqft=c.get("available_sqft"), footprint_sqft=c.get("area_sqft"), stories=c.get("stories_est"),
                        ground_floor_required=ground_required)
    if graded:
        score += W_SIZE * graded.score
        if not best or graded.status != "strong":
            reasons.append(("Size: " if graded.status == "strong" else "Size mismatch: ") + graded.reason)
    else:
        score += W_SIZE * 0.3  # unknown size: not rewarded like a fit, not punished like a mismatch

    near = proximity(c.get("distance_m"))
    if near is not None:
        score += W_NEAR * near
        d, where = c["distance_m"], place_name or "the searched place"
        if d <= 400:
            reasons.append(f"Location: {_distance_text(d)} from {where}")
        elif d > 1000:
            reasons.append(f"Location: {_distance_text(d)} from {where}, at the edge of the area")

    cond = c.get("roof_condition")
    if isinstance(cond, (int, float)):
        score += W_ROOF * (cond - 1) / 4
        if cond >= 4:
            reasons.append(f"Roof in {c.get('roof_condition_label', '').lower()} condition")
        elif cond <= 2:
            reasons.append(f"Roof condition {c.get('roof_condition_label', '').lower()} ({cond:g}/5)")
    else:
        score += W_ROOF * 0.4  # no aerial roof data (e.g. a CoStar-only listing): neutral, not bad

    if best:
        score += W_EVIDENCE  # a real vacancy in range
    elif c.get("space_count"):
        score += W_EVIDENCE * 0.6
    else:
        filled = sum(1 for k in ("building_type", "area_sqft", "roof_condition", "stories_est") if c.get(k) is not None)
        score += W_EVIDENCE * 0.5 * filled / 4
    if program:
        # what the user's program needs from the building (ground floor, ceiling, paving for parking/drive-thru...)
        must = {n["id"] for n in program["needs"] if n["priority"] == "must"} | ({"ground_floor"} if program["building"]["ground_floor"] == "required" else set())
        for chk in space_program.site_checks(program, space_program.facts_from(c, feature)):
            if chk["id"] in {"size", "timeline", "sprinklers", "exits"}:
                continue  # size scored above; the rest are not building-specific at this stage
            if chk["status"] == "risk":
                score -= 10 if chk["id"] in must else 4
                if not (chk["id"] == "ground_floor" and best):  # the listed suite's floor is already explained above
                    reasons.append(f"{chk['label']}: {chk['detail']}")
            elif chk["status"] == "pass" and chk["id"] in must | {"ceiling"}:
                reasons.append(f"{chk['label']}: {chk['detail']}")
    if intent.budget:
        from services.fit_summary import NET_SERVICE, _jurisdiction
        jkey, _ = _jurisdiction(c.get("address"))
        rate = (best or {}).get("rent_per_sqft_yr")
        rent_band = {"per_sqft_low": rate, "per_sqft_high": rate, "source": "CoStar listing"} if rate and best.get("service") in NET_SERVICE else None
        est = costs.estimate(intent.business_type, (best or {}).get("sqft") or size["target_sqft"], jkey, [], False, rent_band)
        check = costs.budget_check(est, intent.budget.model_dump(), intent.business_type)
        # Preserve the existing 0–100 scale while allowing affordability to affect ordering.
        score = score * 0.85 + {"within": 15, "partly": 7, "over": 0}[check["status"]]
        reasons.append(f"Budget (planning estimate): {check['status']}; {check['note']}")
    return max(0, min(round(score), 100)), reasons


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


def attach_costar(candidates: list[dict], lat: float, lon: float, cfg: dict, prog: dict, notes: list[str], radius_m: float = SEARCH_RADIUS_M) -> set[int]:
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
    listed = costar.listed_near(lat, lon, radius_m, types)
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


async def _vexcel_buildings(lat: float, lon: float, source: str, allowed: set[str], notes: list[str]) -> tuple[list[dict], dict[str, dict], float]:
    """Every building in the search area (paged: one Vexcel page is 500 parcels in no particular order, which in a
    dense neighbourhood missed the place itself), widened once when the area holds few suitable buildings.
    Returns (candidates, raw features by id, radius searched)."""
    live = source == "vexcel"
    candidates: list[dict] = []
    raws: dict[str, dict] = {}

    def add(features: list[dict]) -> None:
        for f in features:
            c = vexcel.summarize_feature(f, source=source)
            if c["id"] not in raws:
                candidates.append(c)
                raws[c["id"]] = f

    features, complete = await vexcel.property_sweep(lat, lon, SEARCH_RADIUS_M, calculated=live)
    add(features)
    radius = SEARCH_RADIUS_M
    if not complete:
        notes.append(f"Dense area: the search covered the first {len(features):,} parcels within {SEARCH_RADIUS_M} m.")
    suitable = sum(1 for c in candidates if c.get("building_type") in allowed)
    if suitable < MIN_SUITABLE:
        wide, _ = await vexcel.property_sweep(lat, lon, WIDE_RADIUS_M, max_pages=6, calculated=live)
        add(wide)
        radius = WIDE_RADIUS_M
        notes.append(f"Only {suitable} suitable building(s) within {SEARCH_RADIUS_M} m, so the search widened to {WIDE_RADIUS_M / 1000:.1f} km.")
    return candidates, raws, radius


async def search(query: str, intent: Intent | None = None) -> SearchResponse:
    """Find candidate buildings. `intent` skips parsing for a conversational refinement."""
    intent = intent or await parse(query)
    notes: list[str] = []
    location_text = intent.location_text
    if not location_text:
        location_text = "Houston, TX"
        notes.append("No location in the query, so the search defaults to Houston, TX (inside Vexcel coverage).")
    place = await locate(location_text, notes)
    if not place:
        return SearchResponse(intent=intent, location=None, data_mode="osm_only", candidates=[], notes=[f"Could not find “{location_text}”. Try adding the state."], program=space_program.build(intent))
    lat, lon = place["lat"], place["lon"]
    near_places = []
    for text in intent.near:
        try:
            anchor = await external.geocode(f"{text}, {location_text}")
        except (httpx.HTTPError, ValueError):
            anchor = None
        if anchor:
            near_places.append(anchor)
        else:
            notes.append(f"Could not locate “{text}”; it did not affect ranking.")
    if near_places:
        # Search around the requested landmark, rather than ranking only downtown buildings.
        lat, lon = near_places[0]["lat"], near_places[0]["lon"]
        place = near_places[0]
        notes.append("Proximity ranking uses: " + ", ".join(p["name"] for p in near_places) + ".")
    labels = {n.label.lower() for n in intent.needs}
    extras = [r for r in intent.requirements if r.lower() not in labels]
    if extras or intent.avoid:
        notes.append("Needs to check during analysis (not used to rank discovery): " + "; ".join([*extras, *intent.avoid]) + ".")
    covered = in_coverage(lat, lon)
    location = {"name": place["name"], "lat": lat, "lon": lon, "coverage": covered}

    cfg = business(intent.business_type)
    allowed = set(cfg["suitable_building_types"]) | set(cfg.get("acceptable_building_types", []))
    raws: dict[str, dict | None] = {}
    candidates: list[dict] = []
    radius: float = SEARCH_RADIUS_M
    data_mode = "osm_only"
    if settings.vexcel_api_key and covered:
        try:
            candidates, raws, radius = await _vexcel_buildings(lat, lon, "vexcel", allowed, notes)
            data_mode = "vexcel_live"
        except vexcel.VexcelError as err:
            notes.append(f"Vexcel returned {err.status} ({err.message}); using OpenStreetMap footprints instead.")
        except httpx.HTTPError as err:
            notes.append(f"Vexcel didn't answer ({type(err).__name__}); using OpenStreetMap footprints instead.")
    elif not settings.vexcel_api_key and haversine_m(lat, lon, *DEMO_CENTER) < 6000:
        data_mode = "vexcel_demo"
        notes.append("DEMO MODE: no VEXCEL_API_KEY set, showing a recorded Vexcel sample of downtown Houston.")
        try:
            candidates, raws, radius = await _vexcel_buildings(lat, lon, "demo", allowed, notes)
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
        external.prefetch_places(lat, lon, radius_m=external.PLACES_RADIUS_M + int(radius * 1.42))
    prog = space_program.build(intent)
    listed = attach_costar(candidates, lat, lon, cfg, prog, notes, radius)
    scored: list[Candidate] = []
    seen_ids: set[str] = set()
    ground_only = any(n.id == "ground_floor" and n.priority == "must" for n in intent.needs)
    unknown_ground = 0
    for c in candidates:
        if ground_only:
            ground = (c.get("best_space") or {}).get("ground_floor")
            if ground is None and c.get("stories_est") == 1 and c.get("costar_id"):
                ground = True
            if ground is not True:
                unknown_ground += ground is None
                continue
        if c["id"] in seen_ids:
            continue  # stacked parcels (condos, multi-structure lots) can share a centroid
        seen_ids.add(c["id"])
        if c.get("building_type") and c["building_type"] not in allowed and c.get("costar_id") not in listed:
            continue  # a CoStar lease listing for this use outranks Vexcel's building class
        if c.get("_too_low"):
            continue  # roof under 8 ft: canopy/kiosk/shed rather than a leasable building
        if near_places:
            c["distance_m"] = round(sum(haversine_m(p["lat"], p["lon"], c["lat"], c["lon"]) for p in near_places) / len(near_places))
        else:
            c["distance_m"] = round(haversine_m(lat, lon, c["lat"], c["lon"]))
        distance_label = "requested landmarks (average distance)" if len(near_places) > 1 else place["name"]
        c["match_score"], c["match_reasons"] = prescreen(c, intent, prog, raws.get(c["id"]), distance_label)
        scored.append(Candidate(**c))
    if ground_only:
        notes.append(f"Ground-floor only: excluded {unknown_ground} building(s) with unconfirmed floor; only confirmed street-level matches are shown.")
    # A selected vacancy comes from non-pending CoStar spaces. space_count also includes
    # pending leases, so it must not qualify a property for the available-first group.
    scored.sort(key=lambda c: (not bool(c.best_space), -c.match_score, c.distance_m or 0))
    top = scored[:25]
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
