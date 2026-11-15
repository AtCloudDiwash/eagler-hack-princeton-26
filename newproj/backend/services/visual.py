"""Visual (semantic) matching for discovery via Vexcel /embedding/extract.

Visual needs from the user's request ("outdoor patio", "big parking lot"...) become descriptive phrases
(config/visual_search.yaml). Each phrase returns ~66 m imagery cells ranked by similarity; a candidate's
visual score is the best cell overlapping its footprint or parcel, expressed as a percentile among the
candidates of that search. Similarity is a hint ("looks like a patio"), not proof: the agents still verify.
"""
from __future__ import annotations

import asyncio
import logging

from config import load_yaml, settings
from schemas import Intent
from services import vexcel
from services.geo import centroid, outer_ring, point_in_polygon

log = logging.getLogger("turnkey.visual")
Cell = tuple[float, float, float, float, float]  # (min_lon, min_lat, max_lon, max_lat, score)


def config() -> dict:
    return load_yaml("visual_search.yaml")


def visual_phrases(intent: Intent) -> list[tuple[str, str]]:
    """(need, phrase) pairs for the visual needs in the request, de-duplicated by phrase, capped."""
    cfg = config()
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for need in intent.requirements:
        low = need.lower()
        for keyword, phrase in cfg["phrases"].items():
            if keyword in low and phrase not in seen:
                seen.add(phrase)
                out.append((need, phrase))
                break
    return out[: cfg["max_phrases"]]


def _cells(features: list[dict]) -> list[Cell]:
    cells = []
    for f in features:
        ring = outer_ring(f.get("geometry"))
        score = (f.get("properties") or {}).get("score")
        if ring and isinstance(score, (int, float)):
            lons, lats = [p[0] for p in ring], [p[1] for p in ring]
            cells.append((min(lons), min(lats), max(lons), max(lats), float(score)))
    return cells


async def search_cells(phrase: str, lat: float, lon: float, box_m: float) -> list[Cell]:
    if not settings.vexcel_api_key:
        return []
    n = config()["records"]
    data = await vexcel._get("/embedding/extract", {
        "search-text": phrase, "wkt": f"POINT({lon:.6f} {lat:.6f})", "srid": 4326,
        "buffer-meter": int(box_m), "total-records": n, "page-size": min(n, 500),
    })
    return _cells(data.get("features", []) if isinstance(data, dict) else [])


def best_overlap(candidate: dict, cells: list[Cell]) -> float:
    """Highest score among cells overlapping the building (footprint, else parcel, else its point)."""
    geom = candidate.get("footprint") or candidate.get("parcel")
    ring = outer_ring(geom)
    pts = [(p[0], p[1]) for p in ring] or []
    c = centroid(geom)
    pts.append((c[1], c[0]) if c else (candidate["lon"], candidate["lat"]))
    best = 0.0
    for min_lon, min_lat, max_lon, max_lat, score in cells:
        if score <= best:
            continue
        hit = any(min_lon <= x <= max_lon and min_lat <= y <= max_lat for x, y in pts)
        if not hit and ring:
            hit = point_in_polygon((min_lon + max_lon) / 2, (min_lat + max_lat) / 2, ring)
        if hit:
            best = score
    return best


def percentiles(scores: list[float]) -> list[int]:
    """0-100 rank among candidates with a match (no overlapping strong cell = 0)."""
    positive = sorted(s for s in scores if s > 0)
    if not positive:
        return [0 for _ in scores]
    out = []
    for s in scores:
        if s <= 0:
            out.append(0)
        else:
            below = sum(1 for p in positive if p <= s)
            out.append(round(100 * below / len(positive)))
    return out


async def apply(candidates: list[dict], intent: Intent, lat: float, lon: float, box_m: float) -> str | None:
    """Blend visual similarity into each candidate's match_score in place. Returns a note for the UI."""
    phrases = visual_phrases(intent)
    weight = float(config()["weight"])
    if not phrases or weight <= 0 or not candidates:
        return None
    results = await asyncio.gather(*(search_cells(p, lat, lon, box_m) for _, p in phrases), return_exceptions=True)
    used = []
    per_phrase: list[tuple[str, list[int]]] = []
    for (need, _phrase), cells in zip(phrases, results):
        if isinstance(cells, BaseException) or not cells:
            log.warning("visual search for %r failed or empty: %s", need, cells if isinstance(cells, BaseException) else "no cells")
            continue
        used.append(need)
        per_phrase.append((need, percentiles([best_overlap(c, cells) for c in candidates])))
    if not per_phrase:
        return "Visual search in Vexcel imagery was unavailable; ranked by building fit only."
    for i, c in enumerate(candidates):
        matches = [{"need": need, "pct": pcts[i]} for need, pcts in per_phrase]
        avg = sum(m["pct"] for m in matches) / len(matches)
        c["visual_matches"] = [m for m in matches if m["pct"] > 0]
        c["match_score"] = round((1 - weight) * c["match_score"] + weight * avg)
        for m in sorted(c["visual_matches"], key=lambda m: -m["pct"])[:2]:
            if m["pct"] >= 50:
                c["match_reasons"] = [*c["match_reasons"], f"Looks like: {m['need']} (top {max(1, 100 - m['pct'])}% in imagery)"]
    return f"Visual search: ranked by how much buildings look like {', '.join(repr(u) for u in used)} in Vexcel aerial imagery (similarity, verified later by the agents)."
