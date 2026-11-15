"""Surroundings of a selected building: Vexcel neighbor parcels + OpenStreetMap places within a radius."""
from __future__ import annotations

from collections import Counter
from statistics import mean

from config import settings
from services import external, vexcel
from services.geo import haversine_m


async def neighbor_buildings(lat: float, lon: float, radius_m: int, exclude_id: str | None = None) -> tuple[list[dict], list[dict], str | None]:
    """(summaries, raw features, error) for Vexcel parcels within radius_m."""
    try:
        limit = 150 if radius_m <= 300 else 300 if radius_m <= 800 else 500
        features = await vexcel.property_extract(lat, lon, radius_m * 2, limit=limit)
    except vexcel.VexcelError as err:
        return [], [], f"Vexcel {err.status}: {err.message}"
    out, raws, seen = [], [], set()
    for f in features:
        s = vexcel.summarize_feature(f)
        if s["id"] == exclude_id or s["id"] in seen:
            continue
        seen.add(s["id"])
        d = haversine_m(lat, lon, s["lat"], s["lon"])
        if d <= radius_m:
            s["distance_m"] = round(d)
            out.append(s)
            raws.append(f)
    return out, raws, None


def building_stats(buildings: list[dict], raws: list[dict]) -> tuple[dict, dict]:
    mix = Counter((b.get("building_type") or "unknown") for b in buildings)
    conds = [b["roof_condition"] for b in buildings if isinstance(b.get("roof_condition"), (int, float))]
    vehicles = [f["properties"].get("vehicles.count") for f in raws]
    paved = [f["properties"].get("hardscapes.area") for f in raws]
    residential = sum(mix.get(t, 0) for t in ("single_family", "multiple_family", "condo_apartment", "mobile_home"))
    stats = {
        "buildings": len(buildings),
        "commercial_share_pct": round(100 * mix.get("commercial", 0) / len(buildings)) if buildings else None,
        "residential_buildings": residential,
        "avg_roof_condition": round(mean(conds), 2) if conds else None,
        "poor_roofs": sum(1 for c in conds if c <= 2),
        "vehicles_seen": sum(v for v in vehicles if isinstance(v, (int, float))),
        "paved_area_sqft": round(sum(p for p in paved if isinstance(p, (int, float)))),
    }
    return dict(mix.most_common()), stats


async def build(lat: float, lon: float, radius_m: int, exclude_id: str | None = None) -> dict:
    buildings, raws, verr = await neighbor_buildings(lat, lon, radius_m, exclude_id)
    sources = []
    if verr:
        sources.append({"name": "Vexcel property data", "status": "unavailable", "note": verr})
    else:
        sources.append({"name": "Vexcel property data", "status": "used" if settings.vexcel_api_key else "demo", "note": f"{len(buildings)} parcels within {radius_m} m"})
    mix, stats = building_stats(buildings, raws)

    try:
        all_places = await external.nearby_places(lat, lon)
        places = [p for p in all_places if p["distance_m"] <= radius_m]
        sources.append({"name": "OpenStreetMap places (Overpass)", "status": "used", "note": f"{len(places)} places within {radius_m} m"})
    except Exception as err:  # noqa: BLE001
        places = []
        sources.append({"name": "OpenStreetMap places (Overpass)", "status": "unavailable", "note": str(err)[:160]})
    groups = Counter(external.group_label(p["group"]) for p in places)
    return {
        "center": {"lat": lat, "lon": lon},
        "radius_m": radius_m,
        "buildings": [{k: b[k] for k in ("id", "lat", "lon", "footprint", "building_type", "area_sqft", "roof_condition")} for b in buildings],
        "building_mix": mix,
        "places": places,
        "place_groups": dict(groups.most_common()),
        "stats": stats,
        "sources": sources,
    }
