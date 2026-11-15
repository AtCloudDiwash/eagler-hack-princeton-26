"""FEMA flood hazard zone for a point (National Flood Hazard Layer, public ArcGIS service, no key).

One small request per location (~0.2 s), cached for 30 days. Failures return an explicit "unknown"
result: a missing flood lookup is never reported as "no flood risk".
"""
from __future__ import annotations

import httpx

import db
from config import settings

NFHL_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
SOURCE = "FEMA National Flood Hazard Layer (NFHL)"
SOURCE_URL = "https://msc.fema.gov/portal/home"


def flood_zone(lat: float, lon: float) -> dict:
    """{zone, subtype, sfha (Special Flood Hazard Area, ~1%/yr), moderate (0.2%/yr), status} or status=unknown."""
    key = f"flood:{lat:.4f},{lon:.4f}"
    if (hit := db.cache_get(key, 30 * 86400)) is not None:
        return hit
    params = {
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects", "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
        "returnGeometry": "false", "f": "json",
    }
    try:
        res = httpx.get(NFHL_URL, params=params, timeout=8, headers={"User-Agent": settings.http_user_agent})
        res.raise_for_status()
        features = [f["attributes"] for f in res.json().get("features", [])]
    except (httpx.HTTPError, ValueError, KeyError) as err:
        return {"status": "unknown", "zone": None, "error": f"FEMA flood map unavailable: {err}"}
    if not features:
        out = {"status": "unknown", "zone": None, "error": "No FEMA flood map panel covers this point"}
    else:
        # Several zones can intersect a point on a boundary: report the most hazardous.
        def rank(a: dict) -> int:
            return 2 if a.get("SFHA_TF") == "T" else 1 if "0.2 PCT" in (a.get("ZONE_SUBTY") or "") else 0

        worst = max(features, key=rank)
        sfha = worst.get("SFHA_TF") == "T"
        moderate = not sfha and "0.2 PCT" in (worst.get("ZONE_SUBTY") or "")
        out = {"status": "ok", "zone": worst.get("FLD_ZONE"), "subtype": worst.get("ZONE_SUBTY"), "sfha": sfha, "moderate": moderate}
    db.cache_set(key, out)
    return out
