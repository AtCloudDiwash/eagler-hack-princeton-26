"""Vexcel aerial imagery + property-intelligence adapter.

Mock mode (default): aerial URL and overhead facts (parking count, rooftop HVAC) come from
backend/fixtures/observations.json ('aerial' block); the image is an SVG placeholder in
backend/static/aerials/.

Live mode (USE_MOCK_DATA=false + VEXCEL_API_KEY), for a property with coordinates:

    GET {VEXCEL_API_BASE_URL}/ortho/extract      top-down orthophoto (JPEG)
    GET {VEXCEL_API_BASE_URL}/oriented/extract   north-facing oblique photo (JPEG)
    GET {VEXCEL_API_BASE_URL}/property/extract   AI property attributes (GeoJSON)

The key travels only in the `X-API-KEY` header. Responses are cached on disk under
backend/static/vexcel-cache/<property_id>/ (gitignored: Vexcel imagery is licensed) and served
to the browser from /static, so the key never reaches the frontend and repeat analyses make no
calls. Each item falls back independently: imagery can exist where property data 404s, and the
account is geofenced (403 outside Los Angeles / Houston). Failures fall back to the fixtures.

Live property attributes are normalized into Evidence facts (see `normalize_property_extract`);
they take precedence over fixture facts of the same key, and fixture facts fill the gaps.
"""
from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from ..config import BACKEND_DIR, log, settings
from ..models import Evidence, Property
from ._fixtures import load_fixture

CACHE_DIR = BACKEND_DIR / "static" / "vexcel-cache"
CACHE_URL_PREFIX = "/static/vexcel-cache"
ATTRIBUTION = "© Vexcel Imaging US, Inc."

# Ground area covered by the requested images (metres, centred on the property point) and the
# ortho image size. The footprint overlay box math relies on these matching the request.
BBOX_METERS = (100.0, 100.0)
ORTHO_PIXELS = (800, 800)
IMAGERY_LAYER = "urban"
OBLIQUE_PRODUCT = "oblique-n"

DEFAULT_TONS_PER_UNIT = 5.0
DEFAULT_SQFT_PER_SPACE = 350.0
PARKING_ESTIMATE_CONFIDENCE = 0.4
HVAC_ESTIMATE_FACTOR = 0.75  # tonnage is a guess on top of the unit detection, so trust it less
EARTH_RADIUS_M = 6_371_008.8

CACHE_FILES = {"ortho": "ortho.jpg", "oblique": "oblique.jpg", "property": "property.json"}

GEOFENCE_REASON = "outside the Vexcel account geofence (403)"
NO_DATA_REASON = "no Vexcel data for this location (404)"

# Transient failures (timeouts, 5xx, network) are remembered in memory for this long so a flaky
# API doesn't add a timeout to every analysis. Permanent ones are stored in the cache meta.json.
TRANSIENT_RETRY_SECONDS = 600
_failures: dict[tuple[str, str, float, float], tuple[float, str]] = {}


# --------------------------------------------------------------------------------------------
# Fixtures (mock mode, and the fallback for live mode)
# --------------------------------------------------------------------------------------------


def _record(property_id: str) -> dict[str, Any]:
    return load_fixture("observations.json").get(property_id, {})


# --------------------------------------------------------------------------------------------
# Normalization: /property/extract GeoJSON -> Evidence facts (pure functions)
# --------------------------------------------------------------------------------------------


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts into dotted keys. Vexcel already returns mostly-flat dotted keys
    ("roof-objects.ac-unit.count"); this makes nested and flat shapes look the same."""
    if not isinstance(obj, dict):
        return {prefix: obj} if prefix else {}
    flat: dict[str, Any] = {}
    for key, value in obj.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(flatten(value, path))
        else:
            flat[path] = value
    return flat


_NUMBER = r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"


def parse_wkt_rings(wkt: str | None) -> list[list[tuple[float, float]]]:
    """Every ring of a WKT (MULTI)POLYGON as a list of (lon, lat) vertices."""
    rings = []
    for ring_text in re.findall(r"\(([^()]+)\)", wkt or ""):
        numbers = [float(n) for n in re.findall(_NUMBER, ring_text)]
        if len(numbers) >= 6:
            rings.append(list(zip(numbers[0::2], numbers[1::2])))
    return rings


def to_local_meters(lon: float, lat: float, center_lon: float, center_lat: float) -> tuple[float, float]:
    """(east, north) metres from the centre point, local equirectangular approximation."""
    east = math.radians(lon - center_lon) * EARTH_RADIUS_M * math.cos(math.radians(center_lat))
    north = math.radians(lat - center_lat) * EARTH_RADIUS_M
    return east, north


def _clip_to_rect(ring: list[tuple[float, float]], half_w: float, half_h: float) -> list[tuple[float, float]]:
    """Sutherland-Hodgman clip of a polygon ring (local metres) to |east|<=half_w, |north|<=half_h."""
    edges = [(0, -half_w, 1), (0, half_w, -1), (1, -half_h, 1), (1, half_h, -1)]  # (axis, limit, inside sign)
    points = ring
    for axis, limit, sign in edges:
        if not points:
            break
        inside = [sign * (pt[axis] - limit) >= 0 for pt in points]
        clipped = []
        for i, current in enumerate(points):
            prev, prev_in = points[i - 1], inside[i - 1]
            if inside[i] != prev_in:
                t = (limit - prev[axis]) / (current[axis] - prev[axis])
                clipped.append((prev[0] + t * (current[0] - prev[0]), prev[1] + t * (current[1] - prev[1])))
            if inside[i]:
                clipped.append(current)
        points = clipped
    return points


def footprint_box(
    rings: list[list[tuple[float, float]]],
    center_lon: float,
    center_lat: float,
    bbox_meters: tuple[float, float] = BBOX_METERS,
) -> list[float] | None:
    """Bounding box, as normalized [x, y, w, h], of the part of the footprint visible on a north-up
    image centred on the point and covering `bbox_meters` (width, height). The rings are clipped
    to the image first, so vertices far off-image don't stretch the box. None if not visible."""
    width, height = bbox_meters
    visible = []
    for ring in rings:
        local = [to_local_meters(lon, lat, center_lon, center_lat) for lon, lat in ring]
        visible += _clip_to_rect(local, width / 2, height / 2)
    if not visible:
        return None
    easts, norths = [p[0] for p in visible], [p[1] for p in visible]
    x0, x1 = (min(easts) + width / 2) / width, (max(easts) + width / 2) / width
    y0, y1 = (height / 2 - max(norths)) / height, (height / 2 - min(norths)) / height
    x0, y0, x1, y1 = (min(1.0, max(0.0, v)) for v in (x0, y0, x1, y1))
    if x1 - x0 < 1e-4 or y1 - y0 < 1e-4:
        return None
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _whole(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(value, 2)


def _score(value: Any) -> float | None:
    number = _number(value)
    return None if number is None else round(min(1.0, max(0.0, number)), 2)


def _primary_structure(properties: dict[str, Any]) -> dict[str, Any]:
    structures = properties.get("structures") or []
    structures = [s for s in structures if isinstance(s, dict)]
    if not structures:
        return {}
    return next((s for s in structures if s.get("primary-structure") is True), structures[0])


def detected_roof_defects(structure: dict[str, Any]) -> list[tuple[str, float | None, float | None]]:
    """[(defect name, score, percent)] for every `roof-defects.<...>.<name>.detected == true`."""
    defects = []
    for key, value in structure.items():
        if key.startswith("roof-defects.") and key.endswith(".detected") and value is True:
            path = key[len("roof-defects."): -len(".detected")]
            name = path.split(".")[-1]
            defects.append((name, _score(structure.get(f"roof-defects.{path}.score")),
                            _number(structure.get(f"roof-defects.{path}.percent"))))
    return defects


def normalize_property_extract(
    data: dict[str, Any],
    center_lon: float,
    center_lat: float,
    *,
    tons_per_unit: float = DEFAULT_TONS_PER_UNIT,
    sqft_per_space: float = DEFAULT_SQFT_PER_SPACE,
    bbox_meters: tuple[float, float] = BBOX_METERS,
    live: bool = True,
) -> dict[str, Evidence]:
    """Turn a /property/extract response (requested with unit-system=imperial) into facts.

    Facts whose source field is null/absent are omitted, so fixtures can fill the gap.
    """
    features = data.get("features") or []
    if not features or not isinstance(features[0], dict):
        return {}
    props = flatten(features[0].get("properties") or {})
    structure = flatten(_primary_structure(features[0].get("properties") or {}))
    date = str(props.get("metadata.ortho-date-estimate") or "")[:10]
    when = f" (Vexcel imagery {date})" if date else " (Vexcel imagery)"
    facts: dict[str, Evidence] = {}

    def add(key: str, value: Any, note: str, confidence: float | None = None, box: list[float] | None = None):
        facts[key] = Evidence(
            key=key, value=value, source="vexcel", note=note + when, confidence=confidence, box=box, live=live
        )

    units = _number(structure.get("roof-objects.ac-unit.count"))
    if units is not None:
        units = int(units)
        unit_score = _score(structure.get("roof-objects.ac-unit.score"))
        add("rooftop_hvac_units", units, f"{units} rooftop AC unit(s) detected by Vexcel AI", unit_score)
        add(
            "hvac_tons",
            _whole(units * tons_per_unit),
            f"Estimated from {units} rooftop unit(s) at {tons_per_unit:g} tons each",
            None if unit_score is None else round(unit_score * HVAC_ESTIMATE_FACTOR, 2),
        )

    paved = _number(props.get("hardscapes.area"))
    if paved is not None:
        paved_sqft = int(round(paved))
        add("paved_area_sqft", paved_sqft, f"Paved (hardscape) area on the parcel: {paved_sqft:,} sq ft")
        if sqft_per_space > 0:
            spaces = int(paved_sqft // sqft_per_space)
            add(
                "estimated_parking_spaces",
                spaces,
                f"Estimate from {paved_sqft:,} sq ft of paved area at {sqft_per_space:g} sq ft/space "
                "(includes drive aisles and walkways); not a count of striped spaces",
                PARKING_ESTIMATE_CONFIDENCE,
            )

    vehicles = _number(props.get("vehicles.count"))
    if vehicles is not None:
        add("vehicles_count", int(vehicles), f"{int(vehicles)} vehicle(s) visible on the parcel",
            _score(props.get("vehicles.score")))

    condition = _number(structure.get("roof-characteristics.condition"))
    if condition is not None:
        add("roof_condition", _whole(condition), "Vexcel AI roof condition score, 1 (poor) to 5 (excellent)")

    material = structure.get("roof-characteristics.material.class")
    if material:
        add("roof_material", str(material), f"Roof material classified as {material}",
            _score(structure.get("roof-characteristics.material.score")))

    if any(k.startswith("roof-defects.") for k in structure):
        defects = detected_roof_defects(structure)
        names = [name for name, _, _ in defects]
        detail = ", ".join(f"{n} ({p:g}% of roof)" if p is not None else n for n, _, p in defects)
        scores = [s for _, s, _ in defects if s is not None]
        add("roof_defects", names, f"Roof defects detected: {detail}" if names else "No roof defects detected",
            min(scores) if scores else None)

    area = _number(structure.get("footprint.area"))
    box = footprint_box(parse_wkt_rings(structure.get("footprint.wkt")), center_lon, center_lat, bbox_meters)
    if area is not None:
        area_sqft = int(round(area))
        add("building_footprint_sqft", area_sqft, f"Building footprint {area_sqft:,} sq ft (whole building, not the suite)")
    if box is not None:
        add("building_footprint", int(round(area)) if area is not None else None,
            "Building outline from the Vexcel footprint (box drawn on the aerial image)",
            _score(structure.get("roof-characteristics.structure-score")), box)

    building_type = structure.get("building-type.class")
    if building_type:
        add("building_type", str(building_type), f"Building type classified as {building_type}",
            _score(structure.get("building-type.score")))
    return facts


# --------------------------------------------------------------------------------------------
# Live calls + disk cache
# --------------------------------------------------------------------------------------------


@dataclass
class LiveFetch:
    """Outcome of the three live calls for one property. `errors` maps item -> reason."""

    ortho_url: str | None = None
    oblique_url: str | None = None
    property_data: dict[str, Any] | None = None
    errors: dict[str, str] = field(default_factory=dict)


def clear_failure_cache() -> None:
    _failures.clear()


def _redact(text: str) -> str:
    key = settings.vexcel_api_key
    return text.replace(key, "***") if key else text


def _safe_id(property_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", property_id).strip("_")
    return safe or "property"


def _wkt(prop: Property) -> str:
    return f"POINT({prop.longitude} {prop.latitude})"


def _request_params(item: str, prop: Property) -> tuple[str, dict[str, Any]]:
    bbox = f"{BBOX_METERS[0]:g},{BBOX_METERS[1]:g}"
    common = {"wkt": _wkt(prop), "srid": 4326}
    if item == "ortho":
        return "/ortho/extract", {
            **common, "layer": IMAGERY_LAYER, "bbox-dimensions": bbox,
            "destination-dimensions": f"{ORTHO_PIXELS[0]},{ORTHO_PIXELS[1]}", "image-format": "jpeg",
        }
    if item == "oblique":
        return "/oriented/extract", {
            **common, "layer": IMAGERY_LAYER, "product-type": OBLIQUE_PRODUCT, "bbox-dimensions": bbox,
            "image-format": "jpeg",
        }
    return "/property/extract", {**common, "unit-system": "imperial", "total-records": 1}


def _describe_failure(exc: Exception) -> tuple[str, bool]:
    """(reason without secrets, permanent?) for a failed live call."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 403:
            return GEOFENCE_REASON, True
        if code == 404:
            return NO_DATA_REASON, True
        return f"HTTP {code}", 400 <= code < 500
    if isinstance(exc, httpx.TimeoutException):
        return f"timed out after {settings.provider_timeout_seconds:g}s", False
    if isinstance(exc, ValueError):  # unusable content (not an image / no features / bad JSON)
        return _redact(f"unusable response: {exc}")[:200], True
    return _redact(f"{type(exc).__name__}: {exc}")[:200], False


def _download(item: str, prop: Property) -> bytes:
    """One live call. Returns the bytes to cache; raises on any failure."""
    path, params = _request_params(item, prop)
    response = httpx.get(
        f"{settings.vexcel_api_base_url}{path}",
        params=params,
        headers={"X-API-KEY": settings.vexcel_api_key or ""},
        timeout=settings.provider_timeout_seconds,
    )
    response.raise_for_status()
    content = response.content
    if item == "property":
        data = json.loads(content)
        if not isinstance(data, dict) or not data.get("features"):
            raise ValueError("property/extract returned no features")
    elif not (response.headers.get("content-type", "").startswith("image/") or content[:2] == b"\xff\xd8"):
        raise ValueError(f"expected an image, got {response.headers.get('content-type') or 'unknown content'}")
    return content


def _write_atomic(path: Path, content: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(path)


def _read_meta(folder: Path, prop: Property) -> dict[str, Any] | None:
    """The cache folder's meta.json, or None when absent or fetched for other coordinates."""
    try:
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        same = abs(meta["latitude"] - prop.latitude) < 1e-7 and abs(meta["longitude"] - prop.longitude) < 1e-7
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return meta if same else None


def fetch_live(prop: Property, force_refresh: bool = False) -> LiveFetch:
    """Ortho + oblique + property data for `prop`, from the disk cache or the live API.

    Each item succeeds or fails on its own; this never raises. Permanent failures (403 geofence,
    404 no data, unusable content) are remembered in meta.json; transient ones (timeouts, 5xx,
    network) are retried after TRANSIENT_RETRY_SECONDS. force_refresh re-requests everything.
    """
    result = LiveFetch()
    if prop.latitude is None or prop.longitude is None:
        result.errors = {item: "no coordinates" for item in CACHE_FILES}
        return result
    safe = _safe_id(prop.id)
    folder = CACHE_DIR / safe
    meta = None if force_refresh else _read_meta(folder, prop)
    known_errors: dict[str, str] = dict((meta or {}).get("errors") or {})
    now = time.monotonic()

    to_fetch = []
    for item, filename in CACHE_FILES.items():
        transient_key = (prop.id, item, prop.latitude, prop.longitude)
        if force_refresh:
            _failures.pop(transient_key, None)
        if meta is not None and (folder / filename).exists():
            continue
        if item in known_errors:
            result.errors[item] = known_errors[item]
        elif transient_key in _failures and now - _failures[transient_key][0] < TRANSIENT_RETRY_SECONDS:
            result.errors[item] = _failures[transient_key][1]
        else:
            to_fetch.append(item)

    if to_fetch:
        folder.mkdir(parents=True, exist_ok=True)
        if meta is None:  # new, moved or refreshed: drop old files so a failed item can't serve stale data
            for filename in CACHE_FILES.values():
                (folder / filename).unlink(missing_ok=True)
        with ThreadPoolExecutor(max_workers=len(to_fetch)) as pool:
            futures = {item: pool.submit(_download, item, prop) for item in to_fetch}
        for item, future in futures.items():
            transient_key = (prop.id, item, prop.latitude, prop.longitude)
            try:
                _write_atomic(folder / CACHE_FILES[item], future.result())
                known_errors.pop(item, None)
                _failures.pop(transient_key, None)
            except Exception as exc:  # noqa: BLE001 - every failure falls back per item
                reason, permanent = _describe_failure(exc)
                result.errors[item] = reason
                if permanent:
                    known_errors[item] = reason
                else:
                    _failures[transient_key] = (now, reason)
                log.warning("Vexcel %s for %s unavailable: %s; using fallback", item, prop.id, reason)
        new_meta = {
            "latitude": prop.latitude, "longitude": prop.longitude,
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "errors": known_errors,
        }
        _write_atomic(folder / "meta.json", json.dumps(new_meta, indent=2).encode())

    for item, attr in (("ortho", "ortho_url"), ("oblique", "oblique_url")):
        if item not in result.errors and (folder / CACHE_FILES[item]).exists():
            setattr(result, attr, f"{CACHE_URL_PREFIX}/{safe}/{CACHE_FILES[item]}")
    if "property" not in result.errors and (folder / CACHE_FILES["property"]).exists():
        try:
            result.property_data = json.loads((folder / CACHE_FILES["property"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            result.errors["property"] = f"unreadable cache ({type(exc).__name__})"
    return result


def _threshold(evaluator_name: str, key: str, default: float) -> float:
    """A threshold from the criteria registry (e.g. hvac tons_per_unit), so normalization and the
    evaluators agree. Falls back to `default` if the registry can't be read."""
    from ..services.criteria_manager import load_criteria  # lazy: services import providers

    try:
        for criterion in load_criteria():
            if criterion.evaluator == evaluator_name and key in criterion.thresholds:
                return float(criterion.thresholds[key])
    except Exception:  # noqa: BLE001 - a registry problem is reported elsewhere
        pass
    return default


def live_facts(prop: Property, property_data: dict[str, Any] | None) -> dict[str, Evidence]:
    if not property_data or prop.latitude is None or prop.longitude is None:
        return {}
    return normalize_property_extract(
        property_data,
        prop.longitude,
        prop.latitude,
        tons_per_unit=_threshold("hvac_checker", "tons_per_unit", DEFAULT_TONS_PER_UNIT),
        sqft_per_space=_threshold("parking_checker", "sqft_per_space", DEFAULT_SQFT_PER_SPACE),
    )


# --------------------------------------------------------------------------------------------
# Public interface
# --------------------------------------------------------------------------------------------


def _is_live(prop: Property) -> bool:
    return (
        settings.provider_mode(settings.vexcel_api_key) == "live"
        and prop.latitude is not None
        and prop.longitude is not None
    )


def get_aerial(prop: Property, force_refresh: bool = False) -> dict[str, Any]:
    """Aerial + oblique image links and overhead facts for a property.

    Returns aerial_url, oblique_url, aerial_source ("vexcel-live" | "placeholder"),
    aerial_attribution, observations (raw fixture facts), live_observations (Evidence from the
    live property/extract call, which win over fixture facts of the same key) and errors.
    """
    record = _record(prop.id)
    out: dict[str, Any] = {
        "aerial_url": record.get("aerial_url"),
        "oblique_url": None,
        "aerial_source": "placeholder",
        "aerial_attribution": None,
        "observations": record.get("aerial", {}),
        "live_observations": {},
        "errors": {},
    }
    if not _is_live(prop):
        return out
    fetched = fetch_live(prop, force_refresh=force_refresh)
    if fetched.ortho_url:
        out.update(aerial_url=fetched.ortho_url, aerial_source="vexcel-live", aerial_attribution=ATTRIBUTION)
    out["oblique_url"] = fetched.oblique_url
    out["live_observations"] = live_facts(prop, fetched.property_data)
    out["errors"] = fetched.errors
    return out


def get_aerial_image(prop: Property) -> dict[str, str | None]:
    """Aerial image URL for a property (prompt 04 interface)."""
    return {"aerial_url": get_aerial(prop)["aerial_url"]}
