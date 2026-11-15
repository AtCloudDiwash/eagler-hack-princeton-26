"""Which space does a linked Matterport scan actually show?

CoStar attaches several Matterport scans to a property, and the first one is not always the leasable space:
at 333 Northbelt it is "Fitness Center" (a building amenity) while "Suite 855" is one of the listed suites.
Every scan exposes a name, address, geolocation and a vision-based property classification, so a scan can
be checked against the building before its interior is used as evidence:

- verified: within MISMATCH_M of the building AND its name/address names this building or suite, captured
            within STALE_YEARS, and (when both are known) on the listed suite's floor
- likely:   within MISMATCH_M, nothing contradicts it — or a verified scan that is older than STALE_YEARS
            (the layout may have changed since), shows another floor/suite, or covers several floors
- amenity:  name or classification looks like a shared amenity (fitness center, lobby, pool, theater...)
- residential: an apartment/condo unit tour ("1BR, 1BA", "2x2", "Studio") — never the commercial space for lease
- mismatch: located more than MISMATCH_M away from the building
- unknown:  the scan carries no location or name to check

`verify_scan` judges one scan; `choose_scan` (analysis time only, cached) looks at the property's other
CoStar-attached scans and an address search when the linked one is an amenity or a mismatch.
`default_scan` is the zero-network pick discovery uses when it auto-links a CoStar scan.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date

import httpx

import db
from services import costar, matterport
from services.geo import haversine_m

log = logging.getLogger("turnkey.scan_identity")

MISMATCH_M = 150
STALE_YEARS = 3  # an older scan may show a previous tenant's layout
MAX_ALTERNATIVES = 10
CHOICE_TTL_S = 7 * 24 * 3600
AMENITY_RE = re.compile(
    r"(?<![a-z])(fitness|gym|theat(?:er|re)|cinema|lobby|amenit(?:y|ies)|pool|conference cent(?:er|re)|clubhouse|"
    r"club house|tenant lounge|lounge|training room|rooftop|roof deck|common area|mail room|leasing office)(?![a-z])"
)
_SUITE_IN_NAME = re.compile(r"(?<![a-z])(?:suite|ste\.?|unit|#)\s*([a-z0-9-]+)")
RESIDENTIAL_RE = re.compile(
    r"(?<![a-z0-9])(\d\s*(?:br|bd|bed(?:room)?s?)|studio|\d\s*x\s*\d|\d(?:\.\d)?\s*ba(?:th)?s?|apartments?|apt|model unit|"
    r"townhomes?|townhouses?|condos?|penthouse|bedrooms?|residences?|multi ?family)(?![a-z])"
)
NOT_THE_SPACE = ("mismatch", "amenity", "residential")  # verdicts that send choose_scan looking for a better scan
_RANK = {"verified": 0, "likely": 1, "unknown": 2, "amenity": 3, "residential": 3, "mismatch": 4}

SEARCH_QUERY = """
query TurnkeyScanSearch($q: String!) {
  models(query: $q, pageSize: 10) { results { id name state created modified floors { id } address { address locality administrativeArea postalCode } geolocation { lat long } } }
}
"""


def looks_like_amenity(text: str | None) -> list[str]:
    """Amenity words found in a scan name/caption/classification ('fitness_sports' counts as fitness)."""
    return sorted({m.group(1) for m in AMENITY_RE.finditer((text or "").lower().replace("_", " "))})


def looks_like_residential(text: str | None) -> list[str]:
    """Apartment-unit words in a scan name/caption ("1BR, 1BA", "2x2", "Studio", "Townhome")."""
    return sorted({m.group(1) for m in RESIDENTIAL_RE.finditer((text or "").lower().replace("_", " "))})


def not_the_space(text: str | None) -> bool:
    """A caption that can't show a commercial suite: a shared amenity or an apartment unit."""
    return bool(looks_like_amenity(text) or looks_like_residential(text))


def default_scan(costar_record: dict | None) -> str | None:
    """Discovery's pick (no network): the first CoStar scan whose caption isn't an amenity or an apartment unit.
    When every captioned scan is one (a lobby, a fitness center, "1BR, 1BA"), nothing is linked: such a tour doesn't
    show the commercial space."""
    if not costar_record:
        return None
    scans = [s for s in costar_record.get("matterport_scans") or [] if isinstance(s, dict) and s.get("id")]
    if scans:
        return next((s["id"] for s in scans if not not_the_space(s.get("caption"))), None)
    models = costar_record.get("matterport_models") or []
    return models[0] if models else None


# ---------------------------------------------------------------- judging one scan

def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _street_key(address: str | None) -> tuple[str, str] | None:
    """('9750', 'tanner') from '9750 Tanner Rd, Houston, TX'."""
    m = re.match(r"\s*(\d+)[a-z]?\s+(?:[nsew]\.?\s+)?([a-z0-9]+)", (address or "").lower())
    return (m.group(1), m.group(2)) if m else None


_ORDINAL = {"ground": 1, "first": 1, "lobby": 1, "plaza": 1, "street": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}


def floor_number(text: object) -> int | None:
    """Building floor from a CoStar floor value (36, "First Floor", "2nd Floor", "Ground") or a scan name ("Floor 12")."""
    if isinstance(text, (int, float)):
        return int(text) if text > 0 else None
    t = str(text or "").strip().lower()
    if not t:
        return None
    for word, n in _ORDINAL.items():
        if re.search(rf"(?<![a-z]){word}(?![a-z])", t):
            return n
    m = re.search(r"(?:floor|fl\.?|level|lvl)\s*(\d{1,3})|(\d{1,3})(?:st|nd|rd|th)?\s*(?:floor|fl\b|level)", t) or re.fullmatch(r"\s*(\d{1,3})\s*", t)
    if not m:
        return None
    return int(next(g for g in m.groups() if g)) if m.groups() else int(m.group(0))


def suite_floor(suite: str | None) -> int | None:
    """Floor implied by a 3-4 digit suite number (Suite 1080 -> 10, Suite 170 -> 1); None when it doesn't follow that convention."""
    m = re.fullmatch(r"(\d{3,4})[a-z]?", (suite or "").strip().lower())
    return int(m.group(1)[:-2]) if m and int(m.group(1)[:-2]) > 0 else None


def scan_age_years(captured: str | None, today: date | None = None) -> float | None:
    try:
        d = date.fromisoformat(str(captured)[:10])
    except (TypeError, ValueError):
        return None
    return round(((today or date.today()) - d).days / 365.25, 1)


def _suite(prop: dict) -> str | None:
    s = str((prop.get("best_space") or {}).get("suite") or "").lower()
    s = re.sub(r"^(suite|ste\.?|unit|#)\s*", "", s.strip())
    return s or None


def assess(model_id: str, ident: dict | None, prop: dict) -> dict:
    """Verdict for one scan's identity against the building (pure; see module docstring)."""
    base = {"model_id": model_id, "name": (ident or {}).get("name"), "address": (ident or {}).get("address"), "distance_m": None, "alternatives_checked": 0}
    if not ident or not (ident.get("name") or ident.get("address") or ident.get("lat") is not None):
        return {**base, "verdict": "unknown", "reason": "The scan has no name, address or location to check against this building."}
    name, address = ident.get("name") or "", ident.get("address") or ""
    dist = None
    if ident.get("lat") is not None and ident.get("lon") is not None and prop.get("lat") is not None and prop.get("lon") is not None:
        dist = round(haversine_m(prop["lat"], prop["lon"], ident["lat"], ident["lon"]))
    base["distance_m"] = dist
    label = f"'{name or model_id}'"
    if dist is not None and dist > MISMATCH_M:
        return {**base, "verdict": "mismatch", "reason": f"Scan {label} is located {dist:,} m from this building" + (f" ({address})" if address else "") + "."}
    amenity = looks_like_amenity(" ".join([name, *(ident.get("classifications") or [])]))
    if amenity:
        return {**base, "verdict": "amenity", "reason": f"Scan {label} looks like a shared building amenity ({', '.join(amenity)}), not the leasable space."}
    residential = looks_like_residential(name)
    if residential:
        return {**base, "verdict": "residential", "reason": f"Scan {label} is an apartment-unit tour ({', '.join(residential)}), not the commercial space for lease."}

    signals = []
    suite = _suite(prop)
    other_suite = None
    hay = _norm(f"{name} {address}")
    if suite:
        if re.search(rf"(?<![a-z0-9]){re.escape(suite)}(?![a-z0-9])", hay):
            signals.append(f"names the listed suite {suite}")
        elif (m := _SUITE_IN_NAME.search(name.lower())) and m.group(1) != suite:
            other_suite = m.group(1)
    bname = _norm(prop.get("building_name"))
    if len(bname) >= 5 and bname in _norm(name):
        signals.append(f"name matches the building '{prop.get('building_name')}'")
    sk = _street_key(prop.get("address"))
    if sk and sk == _street_key(address):
        signals.append("street address matches")
    where = f"{dist} m from the building" if dist is not None else "location not recorded"
    # When was it captured, and which floor does it show?
    age = scan_age_years(ident.get("captured"))
    base.update(captured=ident.get("captured"), age_years=age)
    listed_floor = floor_number((prop.get("best_space") or {}).get("floor")) or suite_floor(suite)
    scan_floor = floor_number(name) or suite_floor(other_suite)
    names_listed_suite = any(s.startswith("names the listed suite") for s in signals)
    base.update(listed_floor=listed_floor, scan_floor=scan_floor if not names_listed_suite else listed_floor,
                floor_match=True if names_listed_suite else (scan_floor == listed_floor if scan_floor and listed_floor else None))
    if other_suite:
        floors = f" (floor {scan_floor} vs the listed suite's floor {listed_floor})" if scan_floor and listed_floor and scan_floor != listed_floor else ""
        return {**base, "verdict": "likely", "reason": f"Scan {label} ({where}) shows suite {other_suite} of this building, not the listed suite {suite}{floors}; treat it as building-level evidence."}
    if signals and dist is not None:
        caveats = []
        if base["floor_match"] is False:
            caveats.append(f"it shows floor {scan_floor}, but the listed suite is on floor {listed_floor}")
        if not names_listed_suite and (ident.get("floor_count") or 0) > 1 and prop.get("best_space"):
            caveats.append(f"it covers {ident['floor_count']} floors (a whole-building scan), not one suite")
        if age is not None and age > STALE_YEARS:
            caveats.append(f"it was captured {ident['captured'][:7]} ({age:.0f} years ago), so the layout may have changed")
        if caveats:
            return {**base, "verdict": "likely", "reason": f"Scan {label} is {where} and " + " and ".join(signals) + ", but " + "; ".join(caveats) + ". Treat it as building-level evidence."}
        return {**base, "verdict": "verified", "reason": f"Scan {label} is {where} and " + " and ".join(signals) + (f"; captured {ident['captured'][:7]}" if ident.get("captured") else "") + "."}
    if signals or dist is not None:
        return {**base, "verdict": "likely", "reason": f"Scan {label}: {where}" + (f"; {', '.join(signals)}" if signals else "; its name and address don't identify this building or suite") + "."}
    return {**base, "verdict": "unknown", "reason": f"Scan {label} has no location, and its name doesn't identify this building."}


async def verify_scan(model_id: str, prop: dict, identity: dict | None = None) -> dict:
    """{"verdict", "reason", "model_id", "name", "address", "distance_m", "alternatives_checked"} for one scan.
    Uses the scan's own data (recorded fixture / cache / live CORE tier); never raises."""
    if identity is None:
        try:
            identity = matterport.summarize(await matterport.fetch_model(model_id))["identity"]
        except Exception as err:  # noqa: BLE001 - an unreadable scan is "unknown", not a crash
            return {"verdict": "unknown", "reason": f"Could not read the scan's identity: {err}", "model_id": model_id, "name": None, "address": None, "distance_m": None, "alternatives_checked": 0}
    return assess(model_id, identity, prop)


# ---------------------------------------------------------------- alternatives

async def fetch_identities(ids: list[str]) -> dict[str, dict | None]:
    """Identity (summarize()['identity']) for several scans in one batched CORE-tier query; None if not accessible."""
    out: dict[str, dict | None] = {}
    todo = []
    for mid in ids:
        hit = db.cache_get(f"matterport:{matterport.CACHE_VERSION}:identity:{mid}", CHOICE_TTL_S)
        if hit is not None:
            out[mid] = hit.get("identity")
        else:
            todo.append(mid)
    todo = [m for m in todo if matterport.parse_model_id(m) == m]  # ids go into the query text: only well-formed ones
    if not todo or not matterport.has_credentials():
        return out
    query = "query TurnkeyScanIdentities {\n" + "\n".join(f'  m{i}: model(id: "{mid}") {{{matterport.IDENTITY_FIELDS}\n    floors {{ id }}\n  }}' for i, mid in enumerate(todo)) + "\n}"
    async with httpx.AsyncClient(timeout=30) as client:
        body = await matterport.post_graphql(client, query)
    data = body.get("data") or {}
    for i, mid in enumerate(todo):
        core = data.get(f"m{i}")
        ident = matterport.summarize({"model_id": mid, "core": core})["identity"] if core else None
        out[mid] = ident
        db.cache_set(f"matterport:{matterport.CACHE_VERSION}:identity:{mid}", {"identity": ident})
    return out


async def search_by_address(prop: dict) -> dict[str, dict]:
    """Scans whose address matches '<street number> <street name>' of the building (Model API search)."""
    m = re.match(r"\s*(\d+[a-z]?)\s+((?:[nsew]\.?\s+)?[a-z0-9]+)", (prop.get("address") or "").lower())
    if not m or not matterport.has_credentials():
        return {}
    phrase = f"{m.group(1)} {m.group(2)}".replace('"', "")
    async with httpx.AsyncClient(timeout=30) as client:
        body = await matterport.post_graphql(client, SEARCH_QUERY, {"q": f'"{phrase}"'})
    results = (((body.get("data") or {}).get("models") or {}).get("results")) or []
    return {r["id"]: matterport.summarize({"model_id": r["id"], "core": r})["identity"] for r in results if r.get("id") and r.get("state") in (None, "active")}


def costar_candidates(prop: dict) -> list[dict]:
    """[{"id", "caption"}] of the scans CoStar attaches to this property (captions only if the index has them)."""
    if prop.get("lat") is None or prop.get("lon") is None:
        return []
    rec = costar.match(prop["lat"], prop["lon"], prop.get("footprint")) if prop.get("costar_id") else None
    if not rec:
        return []
    scans = [s for s in rec.get("matterport_scans") or [] if isinstance(s, dict) and s.get("id")]
    return scans or [{"id": m, "caption": None} for m in rec.get("matterport_models") or []]


def _as_candidates(candidates: list | None, prop: dict) -> list[dict]:
    if candidates is None:
        return costar_candidates(prop)
    return [c if isinstance(c, dict) else {"id": c, "caption": None} for c in candidates if c]


async def _best_alternative(prop: dict, linked: str, candidates: list[dict], search_address: bool) -> tuple[dict | None, int]:
    # amenity captions last, so the batch is spent on likely suites first
    ids = [c["id"] for c in sorted(candidates, key=lambda c: not_the_space(c.get("caption"))) if c["id"] != linked]
    ids = list(dict.fromkeys(ids))[:MAX_ALTERNATIVES]
    identities: dict[str, dict | None] = {}
    try:
        identities.update(await fetch_identities(ids))
    except (httpx.HTTPError, matterport.MatterportError) as err:
        log.info("scan identity batch failed: %s", err)
    if search_address:
        try:
            for mid, ident in (await search_by_address(prop)).items():
                if mid != linked and mid not in identities:
                    identities[mid] = ident
        except (httpx.HTTPError, matterport.MatterportError) as err:
            log.info("scan address search failed: %s", err)
    assessed = [assess(mid, ident, prop) for mid, ident in identities.items() if ident]
    good = [a for a in assessed if a["verdict"] in ("verified", "likely")]
    best = min(good, key=lambda a: (_RANK[a["verdict"]], a["distance_m"] if a["distance_m"] is not None else math.inf)) if good else None
    return best, len(identities)


async def choose_scan(prop: dict, candidates: list | None = None, *, allow_switch: bool = True, search_address: bool = True, use_cache: bool = True) -> dict:
    """The scan to analyze for this property: verify_scan()'s dict for it, plus
    {"linked_model_id", "linked_verdict", "switched", "alternative"}.

    Only when the linked scan is an amenity or a mismatch are other scans checked: the property's
    CoStar-attached scans (`candidates`: ids or {"id","caption"}; default from the CoStar index) and an
    address search. With allow_switch=False (a user-chosen link) the better scan is only reported in
    "alternative". Never raises; the alternatives search is cached per property and linked scan."""
    linked = prop.get("matterport_model_id")
    first = await verify_scan(linked, prop)
    out = {**first, "linked_model_id": linked, "linked_verdict": first["verdict"], "switched": False, "alternative": None}
    if first["verdict"] not in NOT_THE_SPACE or not matterport.has_credentials():
        return out
    key = f"matterport:{matterport.CACHE_VERSION}:choose:{prop.get('id')}:{linked}"
    hit = db.cache_get(key, CHOICE_TTL_S) if use_cache else None
    if hit is None:
        try:
            best, checked = await _best_alternative(prop, linked, _as_candidates(candidates, prop), search_address)
        except Exception as err:  # noqa: BLE001 - identity checks must never sink the analysis
            log.warning("choose_scan failed: %s", err)
            best, checked = None, 0
        hit = {"best": best, "checked": checked}
        db.cache_set(key, hit)
    out["alternatives_checked"] = hit["checked"]
    best = hit["best"]
    if not best:
        return out
    if not allow_switch:
        return {**out, "alternative": best}
    return {**best, "alternatives_checked": hit["checked"], "linked_model_id": linked, "linked_verdict": first["verdict"], "switched": True, "alternative": None,
            "reason": f"{best['reason']} The linked scan {linked} was set aside: {first['reason']}"}
