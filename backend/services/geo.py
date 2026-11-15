"""Small geometry helpers: WKT parsing, distances, point-in-polygon, centroids."""
from __future__ import annotations

import hashlib
import math
import re


def parse_wkt(wkt: str | None) -> dict | None:
    """WKT POLYGON / MULTIPOLYGON -> GeoJSON geometry ([lon, lat])."""
    if not wkt:
        return None
    is_multi = wkt.strip().upper().startswith("MULTIPOLYGON")
    body = re.sub(r"^\s*(MULTI)?POLYGON\s*", "", wkt, flags=re.I).strip()

    def ring(text: str) -> list[list[float]]:
        return [[float(n) for n in pt.split()[:2]] for pt in text.split(",") if pt.strip()]

    def polygon(text: str) -> list[list[list[float]]]:
        text = text.strip().lstrip("(").rstrip(")")
        return [ring(r) for r in re.split(r"\)\s*,\s*\(", text)]

    if is_multi:
        inner = body[1:-1]  # drop the outer parentheses
        polys = re.split(r"\)\)\s*,\s*\(\(", inner)
        return {"type": "MultiPolygon", "coordinates": [polygon(p) for p in polys]}
    return {"type": "Polygon", "coordinates": polygon(body)}


def outer_ring(geom: dict | None) -> list[list[float]]:
    if not geom:
        return []
    if geom["type"] == "Polygon":
        return geom["coordinates"][0]
    if geom["type"] == "MultiPolygon":
        return max((p[0] for p in geom["coordinates"]), key=len)
    return []


def area_sqft(geom: dict | None) -> float | None:
    """Area of a Polygon/MultiPolygon in sq ft (local equirectangular projection; fine at parcel scale)."""
    if not geom or geom.get("type") not in {"Polygon", "MultiPolygon"}:
        return None
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    total = 0.0
    for poly in polys:
        ring = poly[0] if poly else []
        if len(ring) < 3:
            continue
        lat0 = sum(p[1] for p in ring) / len(ring)
        kx, ky = 111_320 * math.cos(math.radians(lat0)), 110_540
        pts = [(x * kx, y * ky) for x, y in ring]
        total += abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2
    return round(total * 10.7639) if total else None


def centroid(geom: dict | None) -> tuple[float, float] | None:
    """Rough centroid (lat, lon) as the vertex average of the outer ring."""
    ring = outer_ring(geom)
    if not ring:
        return None
    lon = sum(p[0] for p in ring) / len(ring)
    lat = sum(p[1] for p in ring) / len(ring)
    return lat, lon


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def point_in_polygon(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi:
            inside = not inside
        j = i
    return inside


def property_id(lat: float, lon: float, prefix: str = "vx") -> str:
    """Vexcel parcels carry no id, so ids are a stable hash of the rounded location."""
    digest = hashlib.sha1(f"{lat:.6f},{lon:.6f}".encode()).hexdigest()[:12]
    return f"{prefix}_{digest}"


# Hackathon key geofence (approximate): Vexcel imagery/property data works in LA and Houston only.
COVERAGE = [
    {"name": "Los Angeles", "south": 33.6, "north": 34.45, "west": -118.75, "east": -117.6},
    {"name": "Houston", "south": 29.45, "north": 30.2, "west": -95.85, "east": -94.95},
]


def in_coverage(lat: float, lon: float) -> bool:
    return any(c["south"] <= lat <= c["north"] and c["west"] <= lon <= c["east"] for c in COVERAGE)
