"""CoStar property data (from the sponsor's hackathon kit): rentable area, spaces on the market, asking rents,
building facts (year built, class, parking, sprinklers, ...) and Matterport scans for a building found by discovery.

Vexcel measures the building from the air (footprint), which is NOT the rentable property. CoStar records the
leasing figures: Rentable Building Area (RBA; GLA for retail) and, on lease listings, each available suite's
rentable square feet and asking rent. A building is matched to a CoStar property when the CoStar point falls
inside its footprint, or is the nearest one within MATCH_RADIUS_M.

The index is built once from the kit by scripts/build_costar_index.py (licensed data, gitignored). Without it
everything here returns None and the app falls back to footprint-based estimates.
"""
from __future__ import annotations

import json
import logging
import math
from functools import lru_cache

from config import FIXTURES_DIR
from services.geo import haversine_m, outer_ring, point_in_polygon

log = logging.getLogger("turnkey.costar")
INDEX = FIXTURES_DIR / "costar_index.json"
MATCH_RADIUS_M = 50
_CELL = 0.005  # ~500 m grid buckets for nearest-point lookup


@lru_cache(maxsize=1)
def _index() -> tuple[list[dict], dict[tuple[int, int], list[int]]]:
    if not INDEX.exists():
        return [], {}
    props = json.loads(INDEX.read_text())["properties"]
    grid: dict[tuple[int, int], list[int]] = {}
    for i, p in enumerate(props):
        grid.setdefault((math.floor(p["lat"] / _CELL), math.floor(p["lon"] / _CELL)), []).append(i)
    log.info("CoStar index: %d properties", len(props))
    return props, grid


def available() -> bool:
    return bool(_index()[0])


def match(lat: float, lon: float, footprint: dict | None = None) -> dict | None:
    """The CoStar property for a building: its point inside the footprint, else the nearest within 50 m."""
    props, grid = _index()
    if not props:
        return None
    ci, cj = math.floor(lat / _CELL), math.floor(lon / _CELL)
    near = [props[i] for di in (-1, 0, 1) for dj in (-1, 0, 1) for i in grid.get((ci + di, cj + dj), [])]
    ring = outer_ring(footprint) if footprint else []
    inside = [p for p in near if ring and point_in_polygon(p["lon"], p["lat"], ring)]
    pool = inside or [p for p in near if haversine_m(lat, lon, p["lat"], p["lon"]) <= MATCH_RADIUS_M]
    if not pool:
        return None
    # several CoStar records on one footprint (e.g. a center and its pad): prefer the one with leasing data
    best = min(pool, key=lambda p: (not p["rentable_sqft"], not p["lease_listings"], haversine_m(lat, lon, p["lat"], p["lon"])))
    return {**best, "match": "inside footprint" if inside else f"{haversine_m(lat, lon, best['lat'], best['lon']):.0f} m away"}


def listed_near(lat: float, lon: float, half_box_m: float, types: list[str]) -> list[dict]:
    """CoStar properties of the given types with spaces on the market inside the search box."""
    props, _ = _index()
    dlat, dlon = half_box_m / 110_540, half_box_m / (111_320 * math.cos(math.radians(lat)))
    return [p for p in props if abs(p["lat"] - lat) <= dlat and abs(p["lon"] - lon) <= dlon and p["type"] in types
            and any(s for l in p["lease_listings"] for s in l["spaces"])]


def is_ground_floor(floor: str | None) -> bool | None:
    """True for street-level suites, False for upper floors, None when CoStar has no floor."""
    if not floor:
        return None
    f = str(floor).strip().lower()
    # CoStar FloorName values (decoded): Ground, First Floor, Lobby and Plaza are at street level
    return f in {"ground", "first floor", "lobby", "plaza", "1", "01", "1st", "g", "gf", "ground floor", "street"}


def candidate_fields(p: dict, need_min: int, need_max: int, target: int, ground_floor: bool = False) -> dict:
    """The CoStar figures a discovery candidate carries (the full summary is served with the property detail).
    The selected space is the closest actual vacancy, whether or not it fits the requested range.
    With ground_floor, street-level suites are preferred (then unknown floor, then upper floors)."""
    s = summarize(p, need_min, need_max)
    rank = lambda x: ({True: 0, None: 1, False: 2}[is_ground_floor(x.get("floor"))] if ground_floor else 0, abs((x["sqft"] or 0) - target))  # noqa: E731
    open_spaces = _available_spaces(p)
    best = min(s["fitting_spaces"] or open_spaces, key=rank) if s["fitting_spaces"] or open_spaces else None
    best = space_at_target(best, target) if best else None
    return {
        "costar_id": p["id"], "building_name": p.get("name"),
        "rentable_sqft": p.get("rentable_sqft"), "rentable_basis": p.get("rentable_basis"),
        "available_sqft": s["available_sqft"], "space_count": s["space_count"],
        "best_space": {**{k: best.get(k) for k in ("listing_id", "suite", "floor", "sqft", "sqft_max", "suggested_portion", "rent_per_sqft_yr", "service", "use", "available_on")},
                       "sqft_min": best.get("sqft_min") if (best.get("sqft_min") or 0) < (best.get("sqft_max") or best.get("sqft") or 0) else None,
                       "ground_floor": is_ground_floor(best.get("floor"))} if best else None,
        "closest_space_sqft": None,
        "asking_rent_per_sqft_yr": s["asking_rent_per_sqft_yr"],
        "costar_type": p.get("type"),  # Office / Retail / Multifamily ... (used for match reasons)
        # building figures for the agents (see services/building_facts.py for the sourced, typed view)
        **{k: s[k] for k in ("gross_sqft", "typical_floor_sqft", "stories", "lot_sqft", "parking_ratio", "year_built", "building_class")},
    }


def reconcile(c: dict, p: dict | None) -> dict:
    """The building figures shown on a candidate, with CoStar's recorded values winning over aerial estimates:
    stories (Vexcel divides roof height by ~13 ft, which overcounts tall floors), total floor area (CoStar gross
    building area instead of footprint × estimated stories) and lot area (Vexcel's parcel can be a synthetic
    Voronoi cell). A Vexcel lot smaller than the building's own footprint is dropped as implausible."""
    out = dict(c)
    if p:
        if p.get("stories"):
            out["stories_est"] = int(p["stories"])
        if p.get("gross_sqft"):
            out["floor_area_est_sqft"] = round(p["gross_sqft"])
        if p.get("lot_sqft"):
            out["parcel_sqft"] = round(p["lot_sqft"])
    fp, lot = out.get("area_sqft"), out.get("parcel_sqft")
    if fp and lot and lot < fp and not (p and p.get("lot_sqft")):
        out["parcel_sqft"] = None
    return out


# Building facts carried in the index (scripts/build_costar_index.py); sparse, so absent means unknown.
BUILDING_KEYS = ("year_built", "year_renovated", "renovated_systems", "building_class", "ceiling_height_ft", "slab_to_slab_ft",
                 "building_height_ft", "construction_material", "subtype", "parking_spaces", "parking_types", "elevators",
                 "has_elevator", "sprinklers", "sprinkler_type", "zoning")


def _yearly_rate(s: dict) -> float | None:
    """Asking rent normalized to $/sq ft/year (CoStar rates are per sq ft; monthly x12)."""
    rate = s.get("rate_high") or s.get("rate_low")
    if not rate:
        return None
    return round(rate * 12, 2) if s.get("rate_basis") == "monthly" else round(rate, 2)


def _available_spaces(p: dict) -> list[dict]:
    """Normalized, non-pending rentable suites for selection and display."""
    return [
        {**space, "sqft": space.get("sqft_max") or space.get("sqft_min"),
         "rent_per_sqft_yr": _yearly_rate(space), "listing_id": listing["listing_id"]}
        for listing in p["lease_listings"]
        for space in listing["spaces"]
        if not space["lease_pending"] and (space.get("sqft_max") or space.get("sqft_min"))
    ]


def summarize(p: dict, need_min: int | None = None, need_max: int | None = None) -> dict:
    """Readable leasing summary; with a size range, the spaces that fit it."""
    spaces = []
    for l in p["lease_listings"]:
        for s in l["spaces"]:
            sq = s.get("sqft_max") or s.get("sqft_min")
            spaces.append({**s, "sqft": sq, "rent_per_sqft_yr": _yearly_rate(s), "listing_id": l["listing_id"]})
    spaces.sort(key=lambda s: s["sqft"] or 0)
    total_avail = sum(s["sqft"] or 0 for s in spaces if not s["lease_pending"]) or None
    fits = [s for s in spaces if s["sqft"] and need_min and need_max and (s.get("sqft_min") or s["sqft"]) <= need_max and s["sqft"] >= need_min and not s["lease_pending"]]
    rents = [s["rent_per_sqft_yr"] for s in spaces if s["rent_per_sqft_yr"]]
    return {
        "costar_id": p["id"], "name": p.get("name"), "address": p.get("address"), "type": p.get("type"), "match": p.get("match"),
        "rentable_sqft": p.get("rentable_sqft"), "rentable_basis": p.get("rentable_basis"),
        "gross_sqft": p.get("gross_sqft"), "typical_floor_sqft": p.get("typical_floor_sqft"), "stories": p.get("stories"),
        "lot_sqft": p.get("lot_sqft"), "parking_ratio": p.get("parking_ratio"),
        "spaces": spaces[:20], "space_count": len(spaces), "available_sqft": total_avail,
        "fitting_spaces": fits[:5],
        "asking_rent_per_sqft_yr": [min(rents), max(rents)] if rents else None,
        "matterport_models": p.get("matterport_models", []),
        "matterport_scans": p.get("matterport_scans") or [{"id": m, "caption": None} for m in p.get("matterport_models", [])],
        **{k: p.get(k) for k in BUILDING_KEYS},
        "listing_condition": next((l["condition"] for l in p["lease_listings"] if l.get("condition")), None),
        "note": "CoStar kit snapshot: availability and asking rents are as recorded in the kit, not live. Asking rent is not the achieved rent; check the service type (NNN vs gross).",
    }


def selected_fields(prop: dict, intent, selection: dict | None = None) -> dict:
    """Resolve a request's selection from the index, never trust client rent/area values."""
    from services import program
    rec = match(prop["lat"], prop["lon"], prop.get("footprint"))
    if not rec:
        if selection:
            raise ValueError("The selected listing is no longer available; search again.")
        return prop
    prog = program.build(intent)
    size = prog["size"]
    fields = candidate_fields(rec, size["min_sqft"], size["max_sqft"], size["target_sqft"], prog["building"]["ground_floor"] == "required")
    if selection:
        if not isinstance(selection, dict) or not all(k in selection for k in ("listing_id", "suite", "floor")):
            raise ValueError("Invalid suite selection; search again.")
        spaces = _available_spaces(rec)
        chosen = next((s for s in spaces if all(s.get(k) == selection.get(k) for k in ("listing_id", "suite", "floor"))), None)
        if not chosen:
            raise ValueError("The selected listing is no longer available; search again.")
        fields["best_space"] = {**space_at_target(chosen, size["target_sqft"]), "ground_floor": is_ground_floor(chosen.get("floor"))}
    return {**prop, **fields, "_selection_resolved": True}


def space_at_target(space: dict, target: int) -> dict:
    """A proposed leasable portion of this suite, never the listing/building total.

    Preserve the advertised bounds; division is a proposal requiring landlord confirmation.
    Fixed-size suites retain their recorded area even when outside the requested band.
    """
    high = space.get("sqft_max") or space.get("sqft")
    low = space.get("sqft_min") or high
    proposed = min(max(target, low), high)
    return {**space, "sqft": proposed, "sqft_max": high, "suggested_portion": low < high and proposed < high}
