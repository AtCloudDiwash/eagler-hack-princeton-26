"""Which 3D tours exist for a building, and which one (if any) shows the suite the user would lease.

Big buildings have many Matterport tours (lobby, gym, a dozen suites) and usually none of the suite that is for
lease. Everything here is fetched live from the Matterport Model API when a building is opened (cached for a day,
nothing prebuilt), in two batched requests:

  1. find the building's tours: models tagged with the building's CoStar property id (`internalId: <id>`),
     models at its street address (`address.streetAddressLines: "<number> <street>"`, kept only when the street
     number matches and they are within ADDRESS_M), and the tour ids CoStar attaches to the building;
  2. details for those tours: capture date (`processing.processingCompletedAt`; `created` is when the model joined
     the account) and measured indoor area.

Each tour is labelled (suite number, floor, kind: suite / floor / common area / apartment / building) and matched
to the listed suite: STRONG when the suite number appears in the tour's name, address line or CoStar caption with no
contradiction (and the measured area, when known, is plausible for the listed size); otherwise there is no match and
the panel says so instead of showing another suite as if it were the user's.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

import db
from services import matterport
from services.geo import haversine_m
from services.scan_identity import STALE_YEARS, floor_number, looks_like_amenity, looks_like_residential, scan_age_years, suite_floor

log = logging.getLogger("turnkey.suite_tours")

CACHE_TTL_S = 24 * 3600
ADDRESS_M = 200  # address-search hits farther than this from the building are other buildings
MAX_TOURS = 30
AREA_RATIO = (0.6, 1.15)  # scanned indoor area / listed rentable sq ft (usable ≈ 80% of rentable)

# Search results and full models differ (search: floors { count }; model: a list of floors). One wrong field makes
# GraphQL reject the whole request, so each shape has its own field list.
_COMMON = "id name state internalId description address { address streetAddressLines } geolocation { lat long }"
TOUR_FIELDS = f"{_COMMON} floors {{ count }}"  # models(query:) search results
MODEL_FIELDS = f"{_COMMON} floors {{ id }}"  # model(id:)
_SUITE_PATTERNS = [
    re.compile(r"(?<![a-z])(?:suite|suit|ste\.?|unit|#)\s*([a-z]?\d{1,5}[a-z]?)(?![a-z0-9])"),
    re.compile(r"^\s*([a-z]?\d{3,5}[a-z]?)\s*[-–·:]\s"),  # "1500 - Wells Fargo Plaza"
]


def norm_suite(text: Any) -> str | None:
    """'Suite 0170' / 'Ste. 170' / '170' -> '170'."""
    t = re.sub(r"^(?:suite|suit|ste\.?|unit|#)\s*", "", str(text or "").strip().lower())
    t = t.lstrip("0") or t
    return t or None


def suite_tokens(*texts: str | None) -> list[str]:
    out: list[str] = []
    for text in texts:
        t = (text or "").lower()
        for pat in _SUITE_PATTERNS:
            for m in pat.finditer(t):
                s = norm_suite(m.group(1))
                if s and s not in out:
                    out.append(s)
    return out


def _street_query(address: str | None) -> str | None:
    m = re.match(r"\s*(\d+[a-z]?)\s+((?:[nsew]\.?\s+)?[a-z0-9]+)", (address or "").lower())
    return f"{m.group(1)} {m.group(2)}" if m else None


def label(raw: dict, prop: dict, caption: str | None = None) -> dict:
    """One tour, labelled: suites named, building floor, kind, distance, capture date, area."""
    lines = ((raw.get("address") or {}).get("streetAddressLines")) or []
    line2 = lines[1] if len(lines) > 1 else None
    name = (raw.get("name") or "").strip()
    from_name = suite_tokens(name, line2 if line2 and re.search(r"\d", line2) else None)
    if line2 and re.fullmatch(r"\s*[a-z]?\d{2,5}[a-z]?\s*", line2.lower()):
        from_name = list(dict.fromkeys([*from_name, norm_suite(line2)]))
    from_caption = suite_tokens(caption)
    text = " ".join(x for x in (name, line2 or "", caption or "") if x)
    kind = ("common area" if looks_like_amenity(text) else "apartment" if looks_like_residential(text)
            else "suite" if from_name or from_caption else "floor" if floor_number(name) else "building")
    floor = floor_number(name) if kind == "floor" else (suite_floor((from_name or from_caption or [None])[0]))
    geo = raw.get("geolocation") or {}
    try:
        lat, lon = float(geo.get("lat")), float(geo.get("long"))
        dist = round(haversine_m(prop["lat"], prop["lon"], lat, lon))
    except (TypeError, ValueError, KeyError):
        dist = None
    conflict = bool(from_name and from_caption and not set(from_name) & set(from_caption))
    return {
        "id": raw["id"], "name": name or raw["id"], "caption": caption, "line2": line2,
        "suites": from_name or from_caption, "caption_conflict": f"named suite {from_name[0]}, CoStar caption says {from_caption[0]}" if conflict else None,
        "kind": kind, "floor": floor, "distance_m": dist, "internal_id": str(raw.get("internalId") or "").strip() or None,
        "captured": None, "age_years": None, "area_sqft": None,
        "floors": raw["floors"].get("count") if isinstance(raw.get("floors"), dict) else (len(raw["floors"]) if isinstance(raw.get("floors"), list) else None),
    }


async def building_tours(prop: dict, record: dict | None, use_cache: bool = True) -> list[dict]:
    """All tours of this building we can find live (see module docstring). [] without credentials. Never raises."""
    if not matterport.has_credentials() or prop.get("lat") is None:
        return []
    pid = (record or {}).get("id") or prop.get("costar_id")
    key = f"matterport:{matterport.CACHE_VERSION}:tours:v2:{pid or prop.get('id')}"
    if use_cache and (hit := db.cache_get(key, CACHE_TTL_S)) is not None:
        return hit["tours"]
    captions = {s["id"]: s.get("caption") for s in (record or {}).get("matterport_scans") or [] if isinstance(s, dict) and s.get("id")}
    kit_ids = [m for m in [*captions, *((record or {}).get("matterport_models") or [])] if matterport.parse_model_id(m) == m]
    kit_ids = list(dict.fromkeys(kit_ids))[:MAX_TOURS]
    street = _street_query(prop.get("address") or (record or {}).get("address"))
    parts, variables = [], {}
    if pid:
        parts.append(f"byId: models(query: $qid, pageSize: 50) {{ results {{ {TOUR_FIELDS} }} }}")
        variables["qid"] = f"internalId: {pid}"
    if street:
        parts.append(f"byAddress: models(query: $qaddr, pageSize: 50) {{ results {{ {TOUR_FIELDS} }} }}")
        variables["qaddr"] = f'address.streetAddressLines: "{street}"'
    parts += [f'k{i}: model(id: "{mid}") {{ {MODEL_FIELDS} }}' for i, mid in enumerate(kit_ids)]
    decl = ", ".join(f"${k}: String!" for k in variables)
    query = f"query TurnkeyBuildingTours{f'({decl})' if decl else ''} {{\n  " + "\n  ".join(parts) + "\n}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            body = await matterport.post_graphql(client, query, variables)
            partial = bool(body.get("errors"))
            if partial and not any((body.get("data") or {}).values()):
                raise matterport.MatterportError("; ".join(e.get("message", "")[:120] for e in body["errors"]))
            data = body.get("data") or {}
            found: dict[str, dict] = {}
            for i, mid in enumerate(kit_ids):
                if data.get(f"k{i}"):
                    found[mid] = {**data[f"k{i}"], "_source": "CoStar attachment"}
            for r in ((data.get("byId") or {}).get("results")) or []:
                found.setdefault(r["id"], {**r, "_source": "CoStar id"})
            for r in ((data.get("byAddress") or {}).get("results")) or []:
                if r["id"] in found:
                    continue
                t = label(r, prop)
                address_line = str(((r.get("address") or {}).get("streetAddressLines") or [""])[0]).lower()
                if street and re.match(rf"^{re.escape(street.split()[0])}(?=\s|$)", address_line.strip()) and (t["distance_m"] is None or t["distance_m"] <= ADDRESS_M):
                    found[r["id"]] = {**r, "_source": "street address"}
            tours = [{**label(r, prop, captions.get(mid)), "source": r["_source"]} for mid, r in found.items() if r.get("state") in (None, "active")][:MAX_TOURS]
            if tours:  # capture dates and measured areas, one batched request
                q = "query TurnkeyTourDetails {\n  " + "\n  ".join(
                    f'd{i}: model(id: "{t["id"]}") {{ processing {{ processingCompletedAt }} dimensionEstimates(units: imperial) {{ areaIndoor }} }}' for i, t in enumerate(tours)) + "\n}"
                detail_body = await matterport.post_graphql(client, q)
                partial = partial or bool(detail_body.get("errors"))
                details = detail_body.get("data") or {}
                for i, t in enumerate(tours):
                    d = details.get(f"d{i}") or {}
                    t["captured"] = ((d.get("processing") or {}).get("processingCompletedAt") or "")[:10] or None
                    t["age_years"] = scan_age_years(t["captured"])
                    area = (d.get("dimensionEstimates") or {}).get("areaIndoor")
                    t["area_sqft"] = round(area) if isinstance(area, (int, float)) and area > 0 else None
    except (httpx.HTTPError, matterport.MatterportError) as err:
        log.warning("tour lookup failed for %s: %s", pid or prop.get("id"), err)
        return []  # not cached: retried next time
    if not partial:  # retry failed aliases next time instead of caching missing tours or measurements for a day
        db.cache_set(key, {"tours": tours})
    return tours


def match(tours: list[dict], space: dict | None) -> dict | None:
    """The tour that shows the listed suite: {"id", "confidence": "strong"|"possible", "signals", "caveats"}, or None."""
    suite = norm_suite((space or {}).get("suite"))
    if not suite:
        return None
    best = None
    for t in tours:
        if t.get("kind") != "suite" or (t.get("distance_m") is not None and t["distance_m"] > ADDRESS_M):
            continue
        if suite not in t["suites"]:
            continue
        signals, caveats = [f"tour names suite {suite}"], []
        confidence = "strong"
        if len(t["suites"]) > 1:
            confidence = "possible"
            caveats.append("tour names multiple suites; confirm which space it shows")
        if t.get("caption_conflict"):
            confidence = "possible"
            caveats.append(t["caption_conflict"])
        listed = (space or {}).get("sqft")
        if t.get("area_sqft") and listed:
            ratio = t["area_sqft"] / listed
            if AREA_RATIO[0] <= ratio <= AREA_RATIO[1]:
                signals.append(f"scanned {t['area_sqft']:,} sq ft fits the listed {listed:,.0f} sq ft")
            else:
                confidence = "possible"
                caveats.append(f"scanned {t['area_sqft']:,} sq ft vs listed {listed:,.0f} sq ft (layout may have changed)")
        if t.get("age_years") and t["age_years"] > STALE_YEARS:
            caveats.append(f"captured {t['captured'][:7]}: may show a previous tenant's build-out")
        cand = {"id": t["id"], "confidence": confidence, "signals": signals, "caveats": caveats, "captured": t.get("captured")}
        if best is None or (cand["confidence"] == "strong", cand["captured"] or "") > (best["confidence"] == "strong", best["captured"] or ""):
            best = cand
    return best


def chips(tour: dict, space: dict | None, matched_id: str | None, confidence: str | None = None) -> list[str]:
    """Short labels for the tour list: what it shows, which floor, when, and how it relates to the user's suite."""
    out = []
    if tour["kind"] == "suite" and tour["suites"]:
        out.append(f"Suite {tour['suites'][0]}")
    elif tour["kind"] != "building":
        out.append(tour["kind"])
    if tour.get("floor"):
        out.append(f"floor {tour['floor']}")
    if tour.get("captured"):
        out.append(tour["captured"][:4])
    if tour["id"] == matched_id:
        out.append("possible suite match" if confidence == "possible" else "your suite")
    elif tour["kind"] == "suite" and (space or {}).get("suite"):
        out.append("not your suite")
    return out


def for_property(tours: list[dict], space: dict | None, linked: str | None) -> dict:
    """The panel's view: every tour labelled, the match for the listed suite, and an honest note when there is none."""
    m = match(tours, space)
    suite = norm_suite((space or {}).get("suite"))
    items = [{**t, "chips": chips(t, space, m["id"] if m else None, m["confidence"] if m else None), "embed_url": matterport.embed_url(t["id"]), "linked": t["id"] == linked} for t in tours]
    items.sort(key=lambda t: (t["id"] != (m or {}).get("id"), t["kind"] != "suite", -(int((t.get("captured") or "0")[:4] or 0))))
    if not tours:
        note = "No 3D tours found for this building."
    elif m:
        note = f"Tour of Suite {suite} found ({m['confidence']})." + (f" {'; '.join(m['caveats'])}." if m["caveats"] else "")
    elif suite:
        note = f"No 3D tour of Suite {suite}; {len(tours)} tour{'s' if len(tours) != 1 else ''} of other parts of the building (building-level context only)."
    else:
        note = f"{len(tours)} tour{'s' if len(tours) != 1 else ''} of this building."
    return {"tours": items, "match": m, "suite": suite, "note": note}
