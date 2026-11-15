"""Vexcel API 2.0 client (https://api.vexcelgroup.com/v2, auth via X-API-KEY header).

Endpoints used (checked against the public OpenAPI spec at /v2/api-docs):
  /ortho/tile        XYZ ortho imagery tiles (layer urban | wide-area)
  /embedding/extract semantic text-to-imagery similarity regions (not named businesses or vacancies)
  /property/extract  GeoJSON parcels + structures with AI-detected attributes around a WKT point
                     (buffer-meter = box width/height; total-records caps billable results;
                     include=precomputed,calculated adds roof height/elevation)

Without a key the client serves a recorded Houston sample (demo mode, clearly labelled upstream).
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from config import FIXTURES_DIR, roof_condition_labels, settings
from services.geo import area_sqft, centroid, haversine_m, parse_wkt, property_id

DEMO_FIXTURE = FIXTURES_DIR / "vexcel_houston_demo.json"
_mem_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL_S = 3600  # in-memory only: licensed data is not persisted beyond selected properties


class VexcelError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def mode() -> str:
    return "live" if settings.vexcel_api_key else "demo"


async def _get(path: str, params: dict[str, Any], expect_json: bool = True) -> Any:
    key = f"{path}?{json.dumps(params, sort_keys=True)}"
    hit = _mem_cache.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL_S:
        return hit[1]
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.get(f"{settings.vexcel_base_url}{path}", params=params, headers={"X-API-KEY": settings.vexcel_api_key or ""})
    if res.status_code != 200:
        try:
            message = res.json().get("message") or res.text[:200]
        except ValueError:
            message = res.text[:200]
        raise VexcelError(res.status_code, message)
    value = res.json() if expect_json else res.content
    if expect_json:
        _mem_cache[key] = (time.time(), value)
    return value


async def tile(z: int, x: int, y: int) -> bytes | None:
    if not settings.vexcel_api_key:
        return None
    layer = "urban" if z >= 14 else "wide-area"
    try:
        return await _get("/ortho/tile", {"layer": layer, "zoom": z, "tile-x": x, "tile-y": y, "image-format": "jpeg"}, expect_json=False)
    except (VexcelError, httpx.HTTPError):
        return None


def _demo_features(lat: float, lon: float, box_m: float, limit: int) -> list[dict]:
    if not DEMO_FIXTURE.exists():
        raise VexcelError(503, "Demo sample not recorded (run backend/scripts/record_demo_fixture.py with a key)")
    data = json.loads(DEMO_FIXTURE.read_text())
    half = box_m / 2
    out = []
    for f in data["features"]:
        c = centroid(f.get("geometry"))
        if c and abs(c[0] - lat) * 111_000 <= half and abs(c[1] - lon) * 96_000 <= half:
            out.append(f)
    out.sort(key=lambda f: haversine_m(lat, lon, *centroid(f["geometry"])))
    return out[:limit]


async def property_extract(lat: float, lon: float, box_m: float, limit: int = 100, calculated: bool = False) -> list[dict]:
    """Up to `limit` (max 500) parcels (GeoJSON features) in a box reaching `box_m` from the point. The API
    returns them in no particular order (often the box's edges first), so in a dense area this is NOT the
    nearest parcels: use property_sweep() to cover an area."""
    if not settings.vexcel_api_key:
        return _demo_features(lat, lon, box_m, limit)
    params: dict[str, Any] = {
        "wkt": f"POINT({lon:.6f} {lat:.6f})",
        "srid": 4326,
        "buffer-meter": int(box_m),
        "total-records": limit,
        "page-size": min(limit, 500),
        "unit-system": "imperial",
    }
    if calculated:
        params["include"] = "precomputed,calculated"
    data = await _get("/property/extract", params)
    return data.get("features", [])


PAGE_SIZE = 500  # the API's cap per request; `total-records` caps the sum over all pages


async def property_sweep(lat: float, lon: float, radius_m: float, max_pages: int = 8, calculated: bool = False) -> tuple[list[dict], bool]:
    """Every parcel in the box reaching `radius_m` from the point, paged (up to max_pages x 500), deduplicated.
    Returns (features, complete); complete is False when the area held more parcels than max_pages could fetch."""
    if not settings.vexcel_api_key:
        return _demo_features(lat, lon, radius_m * 2, 100_000), True
    base: dict[str, Any] = {"wkt": f"POINT({lon:.6f} {lat:.6f})", "srid": 4326, "buffer-meter": int(radius_m),
                            "total-records": PAGE_SIZE * max_pages, "page-size": PAGE_SIZE, "unit-system": "imperial"}
    if calculated:
        base["include"] = "precomputed,calculated"

    async def page(n: int) -> list[dict]:
        try:
            return (await _get("/property/extract", {**base, "page": n})).get("features", [])
        except VexcelError as err:
            if n > 1 and err.status == 400 and "past the end" in err.message.lower():
                return []
            raise  # outages and rejected requests do not mean the search is complete

    features: dict[str, dict] = {}
    n, last = 1, await page(1)
    batch = [last]
    while True:
        for fs in batch:
            for f in fs:
                features.setdefault(json.dumps(f.get("geometry"), sort_keys=True), f)
        if len(batch[-1]) < PAGE_SIZE or n >= max_pages:
            return list(features.values()), len(batch[-1]) < PAGE_SIZE
        # more pages: fetch up to three at a time
        nxt = list(range(n + 1, min(n + 3, max_pages) + 1))
        batch = await asyncio.gather(*(page(i) for i in nxt))
        n = nxt[-1]
        while len(batch) > 1 and not batch[-1]:
            batch.pop()  # pages past the end come back empty


# ---------------------------------------------------------------- interpretation helpers

def primary_structure(feature: dict) -> dict | None:
    structures = feature.get("properties", {}).get("structures") or []
    return next((s for s in structures if s.get("primary-structure")), structures[0] if structures else None)


def stories_estimate(structure: dict | None) -> int | None:
    """Stories from roof height (calculated field, feet) at ~13 ft per commercial story."""
    if not structure:
        return None
    explicit = structure.get("roof-characteristics.number-of-stories-below-eave")
    if isinstance(explicit, (int, float)) and explicit > 0:
        return int(explicit)
    height = structure.get("roof-characteristics.height")
    if isinstance(height, (int, float)) and height >= 8:  # lower values are canopies or bad elevation data
        return max(1, round(height / 13))
    return None


def summarize_feature(feature: dict, source: str = "vexcel") -> dict:
    """Vexcel feature -> Candidate-shaped dict (without match score)."""
    s = primary_structure(feature) or {}
    footprint = parse_wkt(s.get("footprint.wkt"))
    parcel = feature.get("geometry")
    c = centroid(footprint) or centroid(parcel)
    lat, lon = c if c else (0.0, 0.0)
    cond = s.get("roof-characteristics.condition")
    return {
        "id": property_id(lat, lon),
        "lat": lat,
        "lon": lon,
        "footprint": footprint,
        "parcel": parcel,
        "building_type": s.get("building-type.class"),
        "area_sqft": round(s["footprint.area"]) if isinstance(s.get("footprint.area"), (int, float)) else None,
        "floor_area_est_sqft": round(s["footprint.area"] * stories) if isinstance(s.get("footprint.area"), (int, float)) and (stories := stories_estimate(s)) else None,
        "parcel_sqft": area_sqft(parcel),
        "roof_condition": cond,
        "roof_condition_label": roof_condition_labels().get(int(cond)) if isinstance(cond, (int, float)) else None,
        "stories_est": stories_estimate(s),
        "source": source,
        "address": None,
        **({"_too_low": True} if isinstance(s.get("roof-characteristics.height"), (int, float)) and s["roof-characteristics.height"] < 8 else {}),
    }


def _fmt(v: Any, unit: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        v = round(v, 1)
    if isinstance(v, (int, float)):
        return f"{v:,}{unit}"
    return str(v).replace("_", " ")


def key_facts(feature: dict | None) -> list[dict]:
    """The most useful fields, readable, grouped for the property panel."""
    if not feature:
        return []
    p = feature.get("properties", {})
    s = primary_structure(feature) or {}
    cond = s.get("roof-characteristics.condition.precise-value") or s.get("roof-characteristics.condition")
    # Label from the nearest class (3.6 -> 4 Good), the same class Vexcel reports and the candidate tile shows.
    label = roof_condition_labels().get(max(1, min(5, round(cond)))) if isinstance(cond, (int, float)) else None
    paved = p.get("hardscapes.area")
    facts = [
        ("Building", "Building type", _fmt(s.get("building-type.class")), f"Vexcel AI confidence {s.get('building-type.score')}" if s.get("building-type.score") else None),
        ("Building", "Building footprint", _fmt(s.get("footprint.area"), " sq ft"), "Outline of the whole building seen from above (about one floor). Not the lot, and not the space you would lease."),
        ("Building", "Est. total floor area", _fmt(round(s["footprint.area"] * stories_estimate(s)) if isinstance(s.get("footprint.area"), (int, float)) and stories_estimate(s) else None, " sq ft"), "Footprint × estimated stories (rough)"),
        ("Site", "Lot (parcel) area", _fmt(area_sqft(feature.get("geometry")), " sq ft"), "The whole property: building plus parking, paving and open land"),
        ("Building", "Roof height", _fmt(s.get("roof-characteristics.height"), " ft"), "Calculated from elevation data"),
        ("Building", "Estimated stories", _fmt(stories_estimate(s)), "Roof height ÷ ~13 ft per story (estimate)"),
        ("Building", "Structures on parcel", _fmt(p.get("structure.count")), None),
        ("Roof", "Roof condition", f"{_fmt(cond)} / 5 ({label})" if label else "—", "Vexcel scale: 1 Bad, 2 Poor, 3 Fair, 4 Good, 5 Great"),
        ("Roof", "Roof material", _fmt(s.get("roof-characteristics.material.class")), None),
        ("Roof", "Roof shape", _fmt(s.get("roof-characteristics.shape.value")), None),
        ("Roof", "Ponding / discoloration", _fmt(s.get("roof-defects.discoloration.percent"), "%") if s.get("roof-defects.discoloration.detected") else "None detected", None),
        ("Roof", "Structural damage", "Detected" if s.get("roof-defects.structural-damage.detected") else "None detected", None),
        ("Rooftop equipment", "AC units detected", _fmt(s.get("roof-objects.ac-unit.count")), "Detected in imagery; units can be hidden, ground-mounted or interior"),
        ("Rooftop equipment", "Roof vents", _fmt(s.get("roof-objects.roof-vent.count")), None),
        ("Rooftop equipment", "Solar", "Detected" if (s.get("roof-objects.solar-panel-photovoltaic.count") or 0) > 0 else "None detected", None),
        ("Rooftop equipment", "Skylights", _fmt(s.get("roof-objects.skylight.count")), None),
        ("Site", "Paved (hardscape) area", _fmt(paved, " sq ft") if isinstance(paved, (int, float)) and paved >= 100 else ("None detected" if isinstance(paved, (int, float)) else "—"),
         "~300–350 sq ft per parking space incl. aisles" + ("; under 100 sq ft is a detection artefact, not a lot (structured or street parking is not counted)" if isinstance(paved, (int, float)) and paved < 100 else "")),
        ("Site", "Vehicles on parcel", _fmt(p.get("vehicles.count")), "Count at image capture time"),
        ("Site", "Tree cover", _fmt(p.get("parcel-tree-cover.percent"), "%"), None),
        ("Imagery", "Collection", _fmt(p.get("metadata.collection")), None),
        ("Imagery", "Capture estimate", (p.get("metadata.ortho-date-estimate") or "—")[:10], None),
        ("Imagery", "Resolution", _fmt(p.get("metadata.gsd"), " m/px"), None),
    ]
    return [{"group": g, "label": l, "value": v, "note": n} for g, l, v, n in facts]


def imagery_meta(feature: dict | None) -> dict | None:
    if not feature:
        return None
    p = feature.get("properties", {})
    return {"collection": p.get("metadata.collection"), "date": (p.get("metadata.ortho-date-estimate") or "")[:10] or None, "gsd_m": p.get("metadata.gsd")}


# What each Vexcel field means and what it can NOT tell you. Given to the Vexcel Agent so it reasons
# about detection limits instead of treating "not detected" as "absent".
FIELD_NOTES: dict[str, str] = {
    "roof-characteristics.condition": "AI roof condition: 1 Bad, 2 Poor, 3 Fair, 4 Good, 5 Great (whole roof, not the tenant's suite).",
    "roof-objects.ac-unit.count": "Rooftop AC units DETECTED in imagery. 0 means none were seen; HVAC may be ground-mounted, split systems, obscured or on another roof level. Not proof of no HVAC.",
    "roof-objects.roof-vent.count": "Small roof penetrations (plumbing/exhaust vents). Many vents suggest existing plumbing/exhaust paths but do not identify kitchen hood exhaust.",
    "roof-characteristics.shape.value": "Flat roofs make it easier to curb-mount new HVAC units and route kitchen exhaust.",
    "roof-characteristics.height": "Calculated roof height above ground (ft). Divide by ~13 ft for commercial stories (estimate).",
    "footprint.area": "Footprint of the whole building (sq ft): its outline seen from above, about one floor. It is NOT the parcel/lot and NOT the leasable space; a tenant usually leases only part of a large or multi-story building.",
    "hardscapes.area": "Paved area on the parcel (sq ft): driveways, lots, walks. ~300-350 sq ft per parking space incl. aisles; not all paving is parking.",
    "vehicles.count": "Vehicles visible on the parcel at capture time: a proxy for parking use/activity, not capacity.",
    "building-type.class": "AI land-use class of the structure (commercial, single_family, condo_apartment, multiple_family...).",
    "roof-defects": "Detected defects: discoloration/water ponding, patches, tarps, debris, structural damage. Percent = share of roof area.",
    "metadata.ortho-date-estimate": "Approximate imagery date; conditions may have changed since.",
}


async def semantic_search(text: str, lat: float, lon: float) -> dict:
    """Visual similarity regions, not verified POIs or available suites.

    Contract: https://api.vexcelgroup.com/v2/api-docs, /embedding/extract.
    """
    if not settings.vexcel_api_key:
        raise VexcelError(401, "Semantic imagery search needs a live Vexcel key")
    result = await _get("/embedding/extract", {
        "search-text": text[:500], "wkt": f"POINT({lon} {lat})", "buffer-meter": 1600,
        "total-records": 12, "page-size": 12, "include": "score,geometry,quadkey,collection",
    })
    features = []
    for feature in result.get("features", []):
        geom, props = feature.get("geometry"), feature.get("properties") or {}
        if not geom or geom.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        features.append({"type": "Feature", "geometry": geom,
                         "properties": {k: props.get(k) for k in ("score", "quadkey", "collection")}})
    return {"type": "FeatureCollection", "features": features}
