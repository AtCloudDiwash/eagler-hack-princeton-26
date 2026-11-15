"""Walking times from a property to nearby points, via the public OSRM foot router (FOSSGIS,
routing.openstreetmap.de; fair use: one request per question, cached). Straight-line circles overstate
what customers can reach when highways, rail or bayous cut the area; walking times show the real reach.
If the router is unavailable, callers get straight-line estimates labelled as such.
"""
from __future__ import annotations

import logging
import math
import time

import httpx

from config import settings

log = logging.getLogger("turnkey.walking")
WALK_M_PER_MIN = 80  # ~4.8 km/h
MAX_DESTINATIONS = 90  # keep each request small (public server)
_cache: dict[str, tuple[float, list[float | None]]] = {}
_TTL = 6 * 3600


def straight_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return math.hypot((lat2 - lat1) * 110_540, (lon2 - lon1) * 111_320 * math.cos(math.radians(lat1)))


def walk_seconds(origin: tuple[float, float], dests: list[tuple[float, float]]) -> tuple[list[float | None], bool]:
    """(seconds per destination, routed?) — routed=False means straight-line estimates."""
    if not dests:
        return [], True
    dests = dests[:MAX_DESTINATIONS]
    key = f"{origin[0]:.5f},{origin[1]:.5f}|" + ";".join(f"{a:.5f},{b:.5f}" for a, b in dests)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1], True
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in [origin, *dests])
    url = f"{settings.walk_router_url.rstrip('/')}/table/v1/foot/{coords}"
    try:
        r = httpx.get(url, params={"sources": "0", "annotations": "duration"}, timeout=15, headers={"User-Agent": settings.http_user_agent})
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok":
            raise ValueError(data.get("message") or data.get("code"))
        secs = list(data["durations"][0][1:])
        _cache[key] = (time.time(), secs)
        return secs, True
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as err:
        log.warning("walking router unavailable, using straight-line estimates: %s", err)
        return [straight_m(*origin, *d) * 1.3 / WALK_M_PER_MIN * 60 for d in dests], False
