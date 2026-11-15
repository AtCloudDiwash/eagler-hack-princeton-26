"""U.S. Census LEHD LODES: where people work (WAC) and where employed people live (RAC), per census block.

Public data, no key. For each state we download three files once (cached on disk under LODES_DIR):
  * {st}_wac_S000_JT00_{year}.csv.gz  jobs located at the workplace block, by industry and earnings
  * {st}_rac_S000_JT00_{year}.csv.gz  employed residents by home block, by earnings
  * {st}_xwalk.csv.gz                  block id -> internal point (lat/lon)
and index them in memory on a ~1 km grid, so radius questions take milliseconds.
Docs: https://lehd.ces.census.gov/data/lodes/LODES8/LODESTechDoc8.pdf
"""
from __future__ import annotations

import csv
import gzip
import logging
import math
import threading
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from config import settings

log = logging.getLogger("turnkey.lodes")
BASE_URL = "https://lehd.ces.census.gov/data/lodes/LODES8"

STATE_CODES = {
    "texas": "tx", "tx": "tx", "california": "ca", "ca": "ca", "new york": "ny", "ny": "ny", "new jersey": "nj", "nj": "nj",
    "florida": "fl", "fl": "fl", "illinois": "il", "il": "il", "pennsylvania": "pa", "pa": "pa", "georgia": "ga", "ga": "ga",
    "washington": "wa", "wa": "wa", "massachusetts": "ma", "ma": "ma", "arizona": "az", "az": "az", "colorado": "co", "co": "co",
}

# NAICS sector columns (CNS01..CNS20) grouped into the signals the agents reason about.
SECTORS = {
    "office": ["CNS09", "CNS10", "CNS11", "CNS12", "CNS13", "CNS14"],  # information, finance, real estate, professional, management, admin
    "food_service": ["CNS18"],  # accommodation & food services
    "retail": ["CNS07"],
    "health_care": ["CNS16"],
    "education": ["CNS15"],
    "arts_recreation": ["CNS17"],
}
EARNINGS = {"low": "CE01", "mid": "CE02", "high": "CE03"}  # <=$1,250 / $1,251-3,333 / >$3,333 per month
CELL = 0.01  # grid cell in degrees (~1.1 km)


def state_code(state: str | None) -> str | None:
    return STATE_CODES.get((state or "").strip().lower())


@dataclass
class _Index:
    workers: dict[tuple[int, int], list[tuple]] = field(default_factory=dict)  # (lat, lon, total, sectors..., earnings...)
    residents: dict[tuple[int, int], list[tuple]] = field(default_factory=dict)  # (lat, lon, total, low, mid, high)


_indexes: dict[str, _Index] = {}
_lock = threading.Lock()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, timeout=120, headers={"User-Agent": settings.http_user_agent}, follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in r.iter_bytes():
                fh.write(chunk)
    tmp.replace(dest)


def _files(st: str) -> dict[str, Path]:
    y = settings.lodes_year
    d = Path(settings.lodes_dir) / st
    files = {
        "wac": (f"{BASE_URL}/{st}/wac/{st}_wac_S000_JT00_{y}.csv.gz", d / f"{st}_wac_S000_JT00_{y}.csv.gz"),
        "rac": (f"{BASE_URL}/{st}/rac/{st}_rac_S000_JT00_{y}.csv.gz", d / f"{st}_rac_S000_JT00_{y}.csv.gz"),
        "xwalk": (f"{BASE_URL}/{st}/{st}_xwalk.csv.gz", d / f"{st}_xwalk.csv.gz"),
    }
    for url, path in files.values():
        if not path.exists():
            log.info("Downloading LODES %s", url)
            _download(url, path)
    return {k: p for k, (_, p) in files.items()}


def _cell(lat: float, lon: float) -> tuple[int, int]:
    return (math.floor(lat / CELL), math.floor(lon / CELL))


def _build(st: str) -> _Index:
    paths = _files(st)
    points: dict[str, tuple[float, float]] = {}
    with gzip.open(paths["xwalk"], "rt") as fh:
        for row in csv.DictReader(fh):
            try:
                points[row["tabblk2020"]] = (float(row["blklatdd"]), float(row["blklondd"]))
            except (KeyError, ValueError):
                continue
    idx = _Index()
    with gzip.open(paths["wac"], "rt") as fh:
        for row in csv.DictReader(fh):
            pt = points.get(row["w_geocode"])
            if not pt:
                continue
            sectors = tuple(sum(int(row[c]) for c in cols) for cols in SECTORS.values())
            earn = tuple(int(row[c]) for c in EARNINGS.values())
            idx.workers.setdefault(_cell(*pt), []).append((pt[0], pt[1], int(row["C000"]), *sectors, *earn))
    with gzip.open(paths["rac"], "rt") as fh:
        for row in csv.DictReader(fh):
            pt = points.get(row["h_geocode"])
            if not pt:
                continue
            idx.residents.setdefault(_cell(*pt), []).append((pt[0], pt[1], int(row["C000"]), *(int(row[c]) for c in EARNINGS.values())))
    return idx


def index(st: str) -> _Index:
    """The state's index, downloading/parsing on first use (a few seconds once, then cached)."""
    with _lock:
        if st not in _indexes:
            _indexes[st] = _build(st)
        return _indexes[st]


def warm(state: str | None) -> None:
    """Load the state's data in the background so the first tool call is instant."""
    st = state_code(state)
    if st and st not in _indexes:
        threading.Thread(target=lambda: _safe_index(st), daemon=True).start()


def _safe_index(st: str) -> None:
    try:
        index(st)
    except Exception as err:  # noqa: BLE001 - warm-up failures resurface on the real call
        log.warning("LODES warm-up for %s failed: %s", st, err)


def _within(cells: dict[tuple[int, int], list[tuple]], lat: float, lon: float, radius_m: float):
    reach = math.ceil(radius_m / 1000 / 1.1) + 1
    c0 = _cell(lat, lon)
    k_lon = 111_320 * math.cos(math.radians(lat))
    for di in range(-reach, reach + 1):
        for dj in range(-reach, reach + 1):
            for rec in cells.get((c0[0] + di, c0[1] + dj), ()):
                if math.hypot((rec[0] - lat) * 110_540, (rec[1] - lon) * k_lon) <= radius_m:
                    yield rec


def workers_within(state: str | None, lat: float, lon: float, radius_m: float) -> dict:
    st = state_code(state)
    if not st:
        raise ValueError(f"No LODES data mapped for state '{state}'")
    idx = index(st)
    total, sectors, earn = 0, [0] * len(SECTORS), [0] * len(EARNINGS)
    for rec in _within(idx.workers, lat, lon, radius_m):
        total += rec[2]
        for i in range(len(SECTORS)):
            sectors[i] += rec[3 + i]
        for i in range(len(EARNINGS)):
            earn[i] += rec[3 + len(SECTORS) + i]
    area_km2 = math.pi * (radius_m / 1000) ** 2
    return {
        "radius_m": int(radius_m),
        "total_jobs": total,
        "jobs_per_km2": round(total / area_km2) if area_km2 else None,
        "by_sector": dict(zip(SECTORS, sectors)),
        "earnings_mix_pct": {k: round(100 * v / total) if total else None for k, v in zip(EARNINGS, earn)},
        "year": settings.lodes_year,
        "state": st,
    }


def residents_within(state: str | None, lat: float, lon: float, radius_m: float) -> dict:
    st = state_code(state)
    if not st:
        raise ValueError(f"No LODES data mapped for state '{state}'")
    idx = index(st)
    total, earn = 0, [0] * len(EARNINGS)
    for rec in _within(idx.residents, lat, lon, radius_m):
        total += rec[2]
        for i in range(len(EARNINGS)):
            earn[i] += rec[3 + i]
    return {
        "radius_m": int(radius_m),
        "employed_residents": total,
        "earnings_mix_pct": {k: round(100 * v / total) if total else None for k, v in zip(EARNINGS, earn)},
        "year": settings.lodes_year,
        "state": st,
    }
