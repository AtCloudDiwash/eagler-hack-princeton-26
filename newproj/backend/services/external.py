"""Non-Vexcel data sources, all keyless except Census ACS:
  - OpenStreetMap Nominatim: geocoding + reverse geocoding (fair use: <= 1 request/second)
  - OpenStreetMap Overpass: nearby places (competitors, demand generators, transit, parking)
  - US Census geocoder (tract lookup, keyless) + ACS 5-year API (needs a free CENSUS_API_KEY)
Results are cached in SQLite (OSM/Census data are openly licensed).
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

import db
from config import place_groups, settings
from services.geo import COVERAGE, haversine_m, in_coverage

HEADERS = {"User-Agent": settings.http_user_agent, "Accept-Language": "en"}
_nominatim_lock = asyncio.Lock()
_last_nominatim = 0.0
_inflight: dict[tuple, asyncio.Task] = {}

OVERPASS_ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
PLACES_RADIUS_M = 1500  # fetched once per property; tools/UI filter to smaller radii locally


async def _nominatim(path: str, params: dict) -> Any:
    global _last_nominatim
    async with _nominatim_lock:
        wait = _last_nominatim + 1.1 - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        _last_nominatim = time.time()
        async with httpx.AsyncClient(timeout=12, headers=HEADERS) as client:
            res = await client.get(f"https://nominatim.openstreetmap.org/{path}", params={**params, "format": "jsonv2"})
        res.raise_for_status()
        return res.json()


_PLACEISH = {"neighbourhood", "suburb", "quarter", "city_district", "borough", "hamlet", "village", "town", "city",
             "locality", "university", "college", "park", "district", "commercial", "retail", "residential"}
_STATE_HINT = re.compile(r",|\b[A-Z]{2}\b|\b(?:texas|california)\b")  # case-sensitive: "TX", not "in"
_ALIASES = [(re.compile(r"\bDTLA\b", re.I), "Downtown Los Angeles"), (re.compile(r"\bLA\b"), "Los Angeles"),
            (re.compile(r"\b(?:HTX|H-Town)\b", re.I), "Houston")]


def expand_aliases(text: str) -> str:
    for pattern, full in _ALIASES:
        text = pattern.sub(full, text)
    return text


def _hit(h: dict, text: str, biased_to: str | None = None) -> dict:
    return {"name": h.get("display_name", text).split(",")[0], "display_name": h.get("display_name"), "lat": float(h["lat"]),
            "lon": float(h["lon"]), "type": h.get("addresstype") or h.get("type"), "biased_to": biased_to}


async def geocode(text: str) -> dict | None:
    """Place name -> point. Ambiguous names ("Montrose", "the Heights", "Midtown") prefer the Vexcel-covered
    metros (Houston, Los Angeles): an in-coverage match among the top results wins, and a bare name with no
    state that only matched elsewhere is retried inside each covered metro (neighbourhood-like places only)."""
    text = expand_aliases(text.strip())
    key = f"geocode:v2:{text.lower()}"
    if (hit := db.cache_get(key, 7 * 86400)) is not None:
        return hit or None
    hits = await _nominatim("search", {"q": text, "limit": 5, "countrycodes": "us", "addressdetails": 1})
    covered = [h for h in hits if in_coverage(float(h["lat"]), float(h["lon"]))]
    result = _hit(covered[0], text) if covered else _hit(hits[0], text) if hits else None
    top = hits[0] if hits else None
    big_city = top is not None and (top.get("addresstype") in {"city", "state"} and float(top.get("importance") or 0) >= 0.6)
    if not covered and not big_city and not _STATE_HINT.search(text):
        for area in COVERAGE:
            box = f"{area['west']},{area['north']},{area['east']},{area['south']}"
            local = await _nominatim("search", {"q": text, "limit": 1, "countrycodes": "us", "viewbox": box, "bounded": 1, "addressdetails": 1})
            if local and (local[0].get("addresstype") or local[0].get("type")) in _PLACEISH:
                result = _hit(local[0], text, area["name"])
                break
    db.cache_set(key, result or {})
    return result


async def reverse(lat: float, lon: float) -> dict:
    key = f"reverse:{lat:.5f},{lon:.5f}"
    if (hit := db.cache_get(key, 30 * 86400)) is not None:
        return hit
    try:
        data = await _nominatim("reverse", {"lat": lat, "lon": lon, "zoom": 18, "addressdetails": 1})
    except httpx.HTTPError:
        return {}
    a = data.get("address", {})
    street = " ".join(x for x in [a.get("house_number"), a.get("road")] if x)
    result = {
        "address": ", ".join(x for x in [street, a.get("city") or a.get("town") or a.get("village"), a.get("state")] if x) or data.get("display_name"),
        "city": a.get("city") or a.get("town") or a.get("village") or a.get("county"),
        "state": a.get("state"),
        "postcode": a.get("postcode"),
        "display_name": data.get("display_name"),
    }
    db.cache_set(key, result)
    return result


# ---------------------------------------------------------------- Overpass places

def _overpass_query(lat: float, lon: float, r: int) -> str:
    around = f"(around:{r},{lat:.6f},{lon:.6f})"
    amenities = "restaurant|fast_food|cafe|bar|pub|food_court|ice_cream|dentist|doctors|clinic|hospital|pharmacy|bank|school|university|college|kindergarten|library|cinema|theatre|parking|fuel|marketplace|community_centre|place_of_worship"
    return (
        f"[out:json][timeout:{90 if r > 1500 else 45}];("
        f'nwr["amenity"~"^({amenities})$"]{around};'
        f'nwr["shop"]{around};'
        f'nwr["leisure"~"^(fitness_centre|sports_centre|park|stadium)$"]{around};'
        f'nwr["office"]{around};'
        f'nwr["tourism"~"^(hotel|attraction|museum)$"]{around};'
        f'nwr["healthcare"]{around};'
        f'node["highway"="bus_stop"]{around};'
        f'nwr["railway"~"^(station|tram_stop|halt)$"]{around};'
        ");out center tags;"
    )


def _classify(tags: dict) -> tuple[str, str] | None:
    """(group id, category) for an OSM tag set using config/place_groups.yaml."""
    for gid, group in place_groups().items():
        for tag, values in group["match"].items():
            v = tags.get(tag)
            if v and ("*" in values or v in values):
                return gid, f"{tag}={v}"
    return None


async def overpass(query: str) -> list[dict]:
    """Run an Overpass query with retries across endpoints; never return silently truncated data."""
    last_error: Exception | None = None
    for url, n in [(url, n) for url in OVERPASS_ENDPOINTS for n in range(2)]:
        if n:
            await asyncio.sleep(4)  # Overpass 502/429/504 are usually transient load shedding
        try:
            async with httpx.AsyncClient(timeout=90, headers=HEADERS) as client:
                res = await client.post(url, data={"data": query})
            res.raise_for_status()
            body = res.json()
            remark = body.get("remark") or ""
            if "error" in remark.lower() or "timed out" in remark.lower():
                raise ValueError(f"Overpass returned partial data: {remark[:120]}")
            return body.get("elements", [])
        except (httpx.HTTPError, ValueError) as err:
            last_error = err
    raise RuntimeError(f"Overpass unavailable: {type(last_error).__name__} {last_error}")


async def _fetch_places(lat: float, lon: float, radius_m: int) -> list[dict]:
    elements = await overpass(_overpass_query(lat, lon, radius_m))
    places = []
    for e in elements:
        tags = e.get("tags", {})
        plat = e.get("lat") or (e.get("center") or {}).get("lat")
        plon = e.get("lon") or (e.get("center") or {}).get("lon")
        cls = _classify(tags)
        if plat is None or plon is None or not cls:
            continue
        if tags.get("amenity") == "parking" and tags.get("access") in {"private", "customers", "no"}:
            continue  # only public parking helps customers
        places.append({
            "id": f"osm_{e['type'][0]}{e['id']}",
            "name": tags.get("name"),
            "category": cls[1],
            "group": cls[0],
            "lat": plat,
            "lon": plon,
            "distance_m": 0,
            "brand": tags.get("brand"),
            "cuisine": tags.get("cuisine"),
        })
    return places


# Places are fetched for an AREA (lat, lon, radius) and reused for any point whose 1.5 km circle fits
# inside it. Discovery prefetches the whole search area so selecting a building is usually instant.
_INDEX_KEY = "places_index"
_TTL = 3 * 86400


def _covering_area(lat: float, lon: float) -> str | None:
    for a in db.cache_get(_INDEX_KEY, _TTL) or []:
        if haversine_m(lat, lon, a["lat"], a["lon"]) + PLACES_RADIUS_M <= a["r"] and db.cache_get(a["key"], _TTL) is not None:
            return a["key"]
    return None


def _covering_inflight(lat: float, lon: float) -> asyncio.Task | None:
    for (alat, alon, r), task in _inflight.items():
        if haversine_m(lat, lon, alat, alon) + PLACES_RADIUS_M <= r:
            return task
    return None


async def _fetch_area(lat: float, lon: float, radius_m: int) -> str:
    akey = (round(lat, 4), round(lon, 4), radius_m)
    task = _inflight.get(akey)
    if task is None:
        task = asyncio.create_task(_fetch_places(lat, lon, radius_m))
        _inflight[akey] = task
    try:
        places = await task
    finally:
        _inflight.pop(akey, None)
    key = f"places:{akey[0]},{akey[1]},{radius_m}"
    db.cache_set(key, places)
    index = [a for a in (db.cache_get(_INDEX_KEY, _TTL) or []) if a["key"] != key]
    db.cache_set(_INDEX_KEY, [*index, {"lat": lat, "lon": lon, "r": radius_m, "key": key}])
    return key


async def nearby_places(lat: float, lon: float) -> list[dict]:
    """All classified places within PLACES_RADIUS_M of the point, nearest first."""
    key = _covering_area(lat, lon)
    if key is None:
        task = _covering_inflight(lat, lon)
        if task is not None:
            try:
                await task
            except Exception:  # noqa: BLE001 - fall through to a dedicated fetch
                pass
            key = _covering_area(lat, lon)
    if key is None:
        key = await _fetch_area(lat, lon, PLACES_RADIUS_M)
    out = []
    for p in db.cache_get(key, _TTL) or []:
        d = haversine_m(lat, lon, p["lat"], p["lon"])
        if d <= PLACES_RADIUS_M:
            out.append({**p, "distance_m": round(d)})
    return sorted(out, key=lambda p: p["distance_m"])


def prefetch_places(lat: float, lon: float, radius_m: int = PLACES_RADIUS_M) -> None:
    """Start the slow Overpass fetch in the background (search area or selected building)."""
    if radius_m == PLACES_RADIUS_M and (_covering_area(lat, lon) or _covering_inflight(lat, lon)):
        return

    async def run() -> None:
        try:
            await _fetch_area(lat, lon, radius_m)
        except Exception:  # noqa: BLE001 - background warmup; errors resurface on the real call
            pass

    asyncio.get_running_loop().create_task(run())


def group_label(gid: str) -> str:
    return place_groups().get(gid, {}).get("label", gid)


# ---------------------------------------------------------------- Census

ACS_VARS = {
    "B01003_001E": "population",
    "B19013_001E": "median_household_income",
    "B01002_001E": "median_age",
    "B25003_003E": "renter_households",
    "B25003_001E": "households",
}


async def census_profile(lat: float, lon: float) -> dict:
    """Census tract for the point and, with CENSUS_API_KEY, ACS 5-year demographics."""
    key = f"census:{lat:.4f},{lon:.4f}:{bool(settings.census_api_key)}"
    if (hit := db.cache_get(key, 30 * 86400)) is not None:
        return hit
    out: dict[str, Any] = {"source": "US Census Bureau", "tract": None, "acs": None, "status": "unavailable", "note": ""}
    try:
        async with httpx.AsyncClient(timeout=15, headers=HEADERS) as client:
            res = await client.get(
                "https://geocoding.geo.census.gov/geocoder/geographies/coordinates",
                params={"x": lon, "y": lat, "benchmark": "Public_AR_Current", "vintage": "Current_Current", "layers": "Census Tracts", "format": "json"},
            )
            tracts = res.json()["result"]["geographies"].get("Census Tracts") or []
            if tracts:
                t = tracts[0]
                out["tract"] = {"state": t["STATE"], "county": t["COUNTY"], "tract": t["TRACT"], "name": t["NAME"]}
            if out["tract"] and settings.census_api_key:
                t = out["tract"]
                res = await client.get(
                    "https://api.census.gov/data/2023/acs/acs5",
                    params={"get": ",".join(ACS_VARS), "for": f"tract:{t['tract']}", "in": f"state:{t['state']} county:{t['county']}", "key": settings.census_api_key},
                )
                rows = res.json()
                values = dict(zip(rows[0], rows[1]))
                acs = {name: (float(values[var]) if values.get(var) not in (None, "", "-666666666") else None) for var, name in ACS_VARS.items()}
                out["acs"] = acs
                out["status"] = "used"
                out["note"] = "ACS 2019-2023 5-year estimates for the census tract"
            elif out["tract"]:
                out["note"] = "Tract identified; demographics need a free CENSUS_API_KEY (api.census.gov/data/key_signup.html)"
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as err:
        out["note"] = f"Census lookup failed: {err}"
    db.cache_set(key, out)
    return out
