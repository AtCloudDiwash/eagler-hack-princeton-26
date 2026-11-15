"""Matterport Model API (GraphQL) client: interior scan data for a building with a linked 3D tour.

A tour is linked to a building either automatically (CoStar attaches Matterport scans to its properties)
or by the user pasting a showcase URL (`https://my.matterport.com/show/?m=<model id>`). Then:

- The 3D tour is always embeddable in the UI (public showcase iframe, no key needed).
- Interior *data* comes from the Model API, which needs an API token whose organization can access the
  model (MATTERPORT_API_KEY = token id, MATTERPORT_API_SECRET = token secret, HTTP Basic auth).
- Responses are cached in SQLite, and a scan recorded with `scripts/record_matterport_fixture.py`
  (backend/fixtures/matterport/<id>.json) is served offline, without credentials.

The data is fetched in independent query tiers, because GraphQL validation is all-or-nothing (one field the
plan can't read fails the whole query):

- CORE (any plan): identity (name, address, geolocation, property classification, publication), floors,
  rooms (label, tags, keywords), labels, notes, Mattertags and measurements the owner added.
- PI (Property Intelligence, Enterprise): area estimates, room classifications (a *residential* classifier:
  Bathroom, Bedroom, Hallway...), ceiling heights, and room boundaries with door and window openings.

A PI failure never loses CORE. Object detection (objectAnnotations) is a limited beta that returns nothing
for our organization, so it is not queried; older recordings that contain it are still read.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import statistics
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

import db
from config import FIXTURES_DIR, settings

log = logging.getLogger("turnkey.matterport")

GRAPH_URL = "https://api.matterport.com/api/models/graph"
FIXTURE_DIR = FIXTURES_DIR / "matterport"
CACHE_TTL_S = 7 * 24 * 3600
CACHE_VERSION = "v4"  # bump when the queries or the raw shape change
# Safety-net recordings (scripts/record_matterport_fixture.py --fallback): served ONLY when the live API fails, so
# a demo survives an outage while the UI keeps showing live data normally. Gitignored like all recordings.
FALLBACK_DIR = FIXTURE_DIR / "fallback"
RETRY_BACKOFF_S = 0.8
_ID_RE = re.compile(r"^[A-Za-z0-9]{11}$")

# Fields every plan can read that tell us WHICH space a scan shows (used by services/scan_identity.py).
IDENTITY_FIELDS = """
    id name state accessVisibility created modified
    processing { processingCompletedAt }
    address { address locality administrativeArea postalCode status }
    geolocation { lat long }
    publication { published url presentedBy }
    propertyClassifications { classification type }"""

CORE_QUERY = f"""
query TurnkeyModelCore($id: ID!) {{
  model(id: $id) {{{IDENTITY_FIELDS}
    description
    floors {{ id label sequence }}
    rooms {{ id label tags keywords floor {{ id label sequence }} }}
    labels {{ label floor {{ id }} }}
    notes {{ id label }}
    mattertagsWithType(include: [default, landmark]) {{ id type label description keywords floor {{ id }} }}
    measurementPaths {{ label lineType distance(units: imperial) }}
  }}
}}
"""

PI_QUERY = """
query TurnkeyModelInsights($id: ID!) {
  model(id: $id) {
    dimensionEstimates(units: imperial) { area areaIndoor areaIndoorWithWalls units }
    floors { id dimensionEstimates(units: imperial) { area areaIndoor areaIndoorWithWalls units } }
    rooms {
      id
      classifications { label confidence defaultKeywords }
      ceiling(units: imperial) { minHeight maxHeight }
      dimensionEstimates(units: imperial) { area areaIndoor areaIndoorWithWalls height width depth units }
      boundary { edges { type openings { type label width height } } }
    }
  }
}
"""

TIERS = {"core": CORE_QUERY, "pi": PI_QUERY}

# Commercial room categories, matched as WHOLE words/phrases against a room's name (or, for rooms without
# a name, the classifier label and tags). The longest matching phrase wins ("open office" -> open_area).
ROOM_TYPES: dict[str, list[str]] = {
    "restroom": ["restroom", "bathroom", "toilet", "wc", "lavatory", "washroom", "powder room", "half bath", "men's room", "women's room"],
    "kitchen": ["kitchen", "kitchenette", "pantry", "breakroom", "break room", "lunchroom", "lunch room", "galley", "prep", "commissary"],
    "office": ["office", "conference", "conference room", "meeting", "meeting room", "boardroom", "study", "private office"],
    "storage": ["storage", "closet", "utility", "utility room", "mechanical", "stockroom", "stock room", "janitor", "electrical room", "server room", "laundry", "garage"],
    "open_area": ["lobby", "showroom", "retail", "sales floor", "dining", "dining room", "open office", "open area", "warehouse", "gym",
                  "exercise room", "studio", "living room", "great room", "family room", "reception", "bullpen"],
}
# Named spaces that are none of the above: a room named like this is NOT re-typed by the classifier.
OTHER_ROOM_TYPES: dict[str, list[str]] = {
    "circulation": ["hallway", "hall", "corridor", "stairs", "staircase", "stairwell", "elevator", "entrance", "entry", "vestibule", "foyer"],
    "exterior": ["balcony", "patio", "exterior", "facade", "driveway", "garden", "pool", "deck", "porch", "yard"],
}
_HIDDEN_KEYWORDS = {"nonarea", "hide"}  # Void / Facade pseudo-rooms
_NOISE_WORDS = {"other", "indoor", "outdoor"}
M_TO_IN = 39.3701
WIDE_DOOR_IN = 96  # overhead / roll-up / dock door territory (or a wide cased opening between areas)
MIN_OPENING_IN = 12  # narrower "openings" are scan artefacts (observed: 0 in)
DOOR_KINDS = {"door-pivot": "hinged door", "door-unknown": "door (type unknown)", "door-sliding": "sliding door", "door-double": "double door"}

ERROR_MESSAGES = {
    "request.unauthenticated": "Matterport rejected the API token (check MATTERPORT_API_KEY / MATTERPORT_API_SECRET).",
    "request.unauthorized": "This Matterport token is not allowed to read {what} (plan or organization permission).",
    "request.invalid": "Matterport rejected the {what} query as invalid (a field may have been removed or renamed): {msg}",
    "error.internal": "Matterport had an internal error while reading {what}; try again shortly.",
    "not.found": "Matterport model {id} was not found, or it isn't shared with this token's organization.",
    "model.inactive": "Matterport model {id} is archived (inactive), so its data can't be read.",
    "quota.exceeded": "The Matterport API quota for this token is used up; try again later.",
}


class MatterportError(Exception):
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------- linking

def parse_model_id(text: str) -> str | None:
    """Model id from a showcase URL (`?m=`), an API/models URL, or a bare 11-character id."""
    text = (text or "").strip()
    if _ID_RE.match(text):
        return text
    try:
        url = urlparse(text if "://" in text else f"https://{text}")
    except ValueError:
        return None
    m = parse_qs(url.query).get("m", [None])[0]
    if m and _ID_RE.match(m):
        return m
    for part in reversed([p for p in url.path.split("/") if p]):
        if _ID_RE.match(part):
            return part
    return None


def embed_url(model_id: str) -> str:
    return f"https://my.matterport.com/show/?m={model_id}&play=1&qs=1&brand=0"


def has_credentials() -> bool:
    return bool(settings.matterport_api_key and settings.matterport_api_secret)


def _fixture_path(model_id: str) -> Path:
    return FIXTURE_DIR / f"{model_id}.json"


def _fallback_path(model_id: str) -> Path:
    return FALLBACK_DIR / f"{model_id}.json"


def _read_fallback(model_id: str, why: str) -> dict | None:
    path = _fallback_path(model_id)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    when = raw.get("recorded_at", "an earlier date")
    note = f"Live Matterport API unavailable ({why[:160]}); using the safety-net copy recorded {when}."
    log.warning("matterport %s: %s", model_id, note)
    return {**raw, "insights_note": " ".join(x for x in (raw.get("insights_note"), note) if x), "served_from": "fallback"}


def data_mode(model_id: str) -> str:
    """'recorded' (fixture on disk), 'live' (API credentials) or 'embed_only' (tour viewable, no data).
    A safety-net recording doesn't change the mode while credentials exist; without them it is 'recorded'."""
    if _fixture_path(model_id).exists():
        return "recorded"
    if has_credentials():
        return "live"
    return "recorded" if _fallback_path(model_id).exists() else "embed_only"


def link_info(prop: dict) -> dict | None:
    model_id = prop.get("matterport_model_id")
    if not model_id:
        return None
    mode = data_mode(model_id)
    note = {
        "recorded": "Interior data from a recorded Model API response (works offline).",
        "live": "Interior data from the Matterport Model API.",
        "embed_only": "3D tour only. Interior data needs MATTERPORT_API_KEY / MATTERPORT_API_SECRET with access to this model.",
    }[mode]
    if prop.get("matterport_note") and prop.get("matterport_auto_model_id") == model_id:
        note = f"{prop['matterport_note']} {note}"
    return {"model_id": model_id, "embed_url": embed_url(model_id), "data": mode, "note": note}


# ---------------------------------------------------------------- Model API

def error_message(err: dict, what: str = "this scan", model_id: str | None = None) -> tuple[str, str | None]:
    """A clear message (and the extensions.code) for one GraphQL error."""
    ext = err.get("extensions") or {}
    # schema validation errors carry no code, only classification=ValidationError
    code = ext.get("code") or ("request.invalid" if ext.get("classification") == "ValidationError" else None)
    msg = (err.get("message") or "").strip()
    template = ERROR_MESSAGES.get(code or "")
    if not template:
        return (msg or "unknown Matterport error"), code
    return template.format(what=what, id=model_id or "?", msg=msg[:200]), code


def _retryable(res: httpx.Response, body: dict | None) -> bool:
    if res.status_code == 429 or res.status_code >= 500:
        return True
    errors = (body or {}).get("errors") or []
    return bool(errors) and not (body or {}).get("data") and any(str((e.get("extensions") or {}).get("retry")).lower() == "true" for e in errors)


async def post_graphql(client: httpx.AsyncClient, query: str, variables: dict | None = None) -> dict:
    """POST a GraphQL query; returns the JSON body ({data, errors}). Retries once on 429/5xx or retry=true."""
    for attempt in (1, 2):
        res = await client.post(
            GRAPH_URL,
            json={"query": query, "variables": variables or {}},
            auth=(settings.matterport_api_key or "", settings.matterport_api_secret or ""),
            headers={"User-Agent": settings.http_user_agent},
        )
        if res.status_code in (401, 403):
            raise MatterportError(ERROR_MESSAGES["request.unauthenticated"], "request.unauthenticated")
        try:
            body = res.json()
        except ValueError:
            body = None
        if attempt == 1 and _retryable(res, body):
            log.info("Matterport API asked for a retry (HTTP %s)", res.status_code)
            await asyncio.sleep(RETRY_BACKOFF_S)
            continue
        if res.status_code == 429:
            raise MatterportError(ERROR_MESSAGES["quota.exceeded"], "quota.exceeded")
        res.raise_for_status()
        if body is None:
            raise MatterportError(f"Matterport returned a non-JSON response (HTTP {res.status_code}).")
        return body
    raise AssertionError("unreachable")


async def _fetch_tier(client: httpx.AsyncClient, tier: str, model_id: str) -> tuple[dict | None, list[str], str | None]:
    """(model data, error messages, first error code). Partial data (some fields errored) is kept."""
    what = "Property Intelligence data (areas, ceilings, doors, windows)" if tier == "pi" else "this scan"
    body = await post_graphql(client, TIERS[tier], {"id": model_id})
    errs = [error_message(e, what, model_id) for e in body.get("errors") or []]
    model = (body.get("data") or {}).get("model")
    return model, [m for m, _ in errs], next((c for _, c in errs if c), None)


async def fetch_model(model_id: str, use_cache: bool = True) -> dict:
    """Raw scan data: {"model_id", "schema", "core", "insights", "insights_note", "tiers"}.
    Recorded fixture > cache > live API > safety-net recording (only when live fails). `insights` is the PI tier
    (None when the plan doesn't include it)."""
    path = _fixture_path(model_id)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    key = f"matterport:{CACHE_VERSION}:{model_id}"
    if use_cache and (hit := db.cache_get(key, CACHE_TTL_S)):
        return hit
    if not has_credentials():
        if (fb := _read_fallback(model_id, "no API credentials configured")) is not None:
            return fb
        raise MatterportError("No Matterport API credentials configured (MATTERPORT_API_KEY / MATTERPORT_API_SECRET).")
    try:
        raw = await _fetch_live(model_id)
    except (httpx.HTTPError, MatterportError, asyncio.TimeoutError, OSError) as err:
        if (fb := _read_fallback(model_id, str(err) or type(err).__name__)) is not None:
            return fb
        raise
    db.cache_set(key, raw)
    return raw


async def _fetch_live(model_id: str) -> dict:
    """Both query tiers from the Model API (CORE failure raises; PI failure only adds a note)."""
    async with httpx.AsyncClient(timeout=30) as client:
        core_res, pi_res = await asyncio.gather(_fetch_tier(client, "core", model_id), _fetch_tier(client, "pi", model_id), return_exceptions=True)
    if isinstance(core_res, BaseException):
        if isinstance(core_res, MatterportError):
            raise core_res
        raise MatterportError(f"Matterport model {model_id} could not be read: {core_res}") from core_res
    core, core_errs, core_code = core_res
    if not core:
        raise MatterportError("; ".join(core_errs) or f"Matterport model {model_id} not found.", core_code)

    insights, note = None, None
    if isinstance(pi_res, BaseException):
        note = f"Property Intelligence (areas, ceilings, doors, windows) unavailable: {pi_res}"
    else:
        insights, pi_errs, _ = pi_res
        if pi_errs:
            note = ("Some Property Intelligence fields are unavailable: " if insights else "Property Intelligence unavailable: ") + "; ".join(pi_errs)[:300]
    if insights is None and note is None:
        note = "Property Intelligence (areas, ceilings, doors, windows) is not enabled for this model (Enterprise feature)."
    return {"model_id": model_id, "schema": 2, "core": core, "insights": insights, "insights_note": note,
            "tiers": {"core": True, "pi": insights is not None}}


# ---------------------------------------------------------------- normalization

def _capture_date(core: dict) -> str | None:
    """When the space was scanned. `created` is when the model joined this account (e.g. copied into an org last
    week); processing completes right after the capture upload, so it dates the scan itself."""
    done = ((core.get("processing") or {}).get("processingCompletedAt") or "")[:10]
    return done or (core.get("created") or "")[:10] or None


def _num(v: Any) -> float | None:
    return round(float(v), 1) if isinstance(v, (int, float)) and v > 0 else None


def _word_re(term: str) -> re.Pattern:
    """Whole-word (or whole-phrase) match, tolerating a plural: 'restroom' matches 'Restrooms', not 'Hallway'."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?:s|es)?(?![a-z0-9])")


_TERM_RES = {t: _word_re(t) for terms in [*ROOM_TYPES.values(), *OTHER_ROOM_TYPES.values()] for t in terms}


def _has_word(text: str, term: str) -> bool:
    return bool((_TERM_RES.get(term) or _word_re(term)).search(text.lower()))


def _category_of(texts: list[str]) -> str | None:
    best: tuple[int, str] | None = None
    hay = " | ".join(t for t in texts if t).lower()
    for cat, terms in [*ROOM_TYPES.items(), *OTHER_ROOM_TYPES.items()]:
        for t in terms:
            if _has_word(hay, t) and (best is None or len(t) > best[0]):
                best = (len(t), cat)
    return best[1] if best else None


def _room_texts(room: dict) -> list[str]:
    """What a room's type is judged from: the scanner's own room name wins over the residential classifier
    (observed: 'Breakroom' classified Balcony, 'Conference Room' classified Hallway)."""
    if room.get("label_source") == "user":
        return [room["label"]]
    return [room.get("type") or "", *[k for k in room.get("keywords") or [] if k.lower() not in _NOISE_WORDS]]


def room_category(room: dict) -> str | None:
    """'restroom' | 'kitchen' | 'office' | 'storage' | 'open_area' | 'circulation' | 'exterior' | None."""
    if room.get("label_source") == "user":
        cat = _category_of([room["label"]])
        if cat:
            return cat
        # a name like "Suite A" says nothing about use: fall back to the classifier
        return _category_of([room.get("type") or "", *[k for k in room.get("keywords") or [] if k.lower() not in _NOISE_WORDS]])
    return _category_of(_room_texts(room))


def _openings(pi_room: dict) -> list[dict]:
    """Door/window openings on a room boundary. The API returns width/height in METRES even with imperial units."""
    out = []
    for edge in (pi_room.get("boundary") or {}).get("edges") or []:
        for o in edge.get("openings") or []:
            if o.get("type") == "divider" or not isinstance(o.get("width"), (int, float)) or o["width"] * M_TO_IN < MIN_OPENING_IN:
                continue  # dividers are virtual boundaries; near-zero widths are reconstruction artefacts
            out.append({
                "type": o.get("type"), "label": o.get("label"),
                "width_in": round(o["width"] * M_TO_IN), "height_in": round(o["height"] * M_TO_IN) if isinstance(o.get("height"), (int, float)) and o["height"] > 0 else None,
                "_key": f"{o.get('type')}|{o.get('label')}|{o.get('width')}|{o.get('height')}",
            })
    return out


def summarize(raw: dict) -> dict:
    """Readable scan summary: identity, floors and rooms (areas, ceilings, openings when available), tags.
    Reads both the current tiered shape and older recordings (classifications in core, `mattertags`)."""
    core = raw.get("core") or {}
    ins = raw.get("insights") or {}
    pi_rooms = {r["id"]: r for r in ins.get("rooms") or [] if r.get("id")}
    floor_dims = {f["id"]: f.get("dimensionEstimates") or {} for f in ins.get("floors") or [] if f.get("id")}
    floors = sorted(core.get("floors") or [], key=lambda f: f.get("sequence") or 0)
    floor_label = {f["id"]: f.get("label") or f"Floor {(f.get('sequence') or 0) + 1}" for f in floors}

    rooms, hidden = [], 0
    for r in core.get("rooms") or []:
        pr = pi_rooms.get(r.get("id"), {})
        classes = sorted(pr.get("classifications") or r.get("classifications") or [], key=lambda c: -(c.get("confidence") or 0))
        keywords = set((r.get("keywords") or []) + (r.get("tags") or []))
        if {k.lower() for k in keywords} & _HIDDEN_KEYWORDS or (classes and {k.lower() for k in classes[0].get("defaultKeywords") or []} & _HIDDEN_KEYWORDS):
            hidden += 1  # Void / Facade: a modelling artefact, not a room
            continue
        rtype = classes[0].get("label") if classes else None
        d = pr.get("dimensionEstimates") or {}
        ceiling = pr.get("ceiling") or {}
        fid = (r.get("floor") or {}).get("id")
        user_label = (r.get("label") or "").strip()
        room = {
            "id": r.get("id"),
            "label": user_label or rtype or "Unlabeled room",
            "label_source": "user" if user_label else "classifier" if rtype else None,
            "type": rtype,
            "type_confidence": round(classes[0]["confidence"], 2) if classes and classes[0].get("confidence") is not None else None,
            "floor": floor_label.get(fid, (r.get("floor") or {}).get("label")),
            "area_sqft": _num(d.get("areaIndoor") or d.get("area")),
            "area_with_walls_sqft": _num(d.get("areaIndoorWithWalls")),
            "height_ft": _num(d.get("height")) or _num(ceiling.get("maxHeight")),
            "ceiling_min_ft": _num(ceiling.get("minHeight")),
            "ceiling_max_ft": _num(ceiling.get("maxHeight")),
            "width_ft": _num(d.get("width")),
            "depth_ft": _num(d.get("depth")),
            "keywords": sorted(keywords)[:12],
            "has_boundary": bool((pr.get("boundary") or {}).get("edges")),
            "openings": _openings(pr),
        }
        room["category"] = room_category(room)
        rooms.append(room)
    room_label = {r["id"]: r["label"] for r in rooms}
    objects = [
        {"label": (o.get("classification") or {}).get("label") or o.get("label"), "confidence": o.get("confidence"), "room": room_label.get((o.get("room") or {}).get("id"))}
        for o in ins.get("objectAnnotations") or []
        if (o.get("classification") or {}).get("label") or o.get("label")
    ]
    model_dims = ins.get("dimensionEstimates") or {}
    total = _num(model_dims.get("areaIndoor") or model_dims.get("area"))
    if total is None and any(r["area_sqft"] for r in rooms):
        total = round(sum(r["area_sqft"] or 0 for r in rooms), 1)
    tags_raw = core.get("mattertagsWithType") if "mattertagsWithType" in core else core.get("mattertags")
    tiers = ["core"] + (["pi"] if ins else []) + (["boundary"] if any(r["has_boundary"] for r in rooms) else []) + (["objects"] if objects else [])
    addr = core.get("address") or {}
    geo = core.get("geolocation") or {}
    return {
        "model_id": raw.get("model_id"),
        "name": (core.get("name") or "").strip() or None,
        "captured": _capture_date(core),
        "floors": [{"label": floor_label[f["id"]], "area_sqft": _num((floor_dims.get(f["id"]) or {}).get("areaIndoor") or (floor_dims.get(f["id"]) or {}).get("area"))} for f in floors],
        "rooms": rooms,
        "total_indoor_area_sqft": total,
        "total_indoor_area_with_walls_sqft": _num(model_dims.get("areaIndoorWithWalls")),
        "objects": objects,
        "tags": [{"label": t.get("label"), "description": (t.get("description") or "")[:200]} for t in tags_raw or [] if t.get("label")],
        "labels": [l.get("label") for l in core.get("labels") or [] if l.get("label")],
        "notes": [n.get("label") or "(note)" for n in core.get("notes") or []],
        "measurements": [{"label": m.get("label"), "length_ft": _num(m.get("distance") if "distance" in m else m.get("lengthFt"))} for m in core.get("measurementPaths") or []],
        "hidden_room_count": hidden,
        "tiers_available": tiers,
        "identity": {
            "name": (core.get("name") or "").strip() or None,
            "address": addr.get("address"), "locality": addr.get("locality"), "region": addr.get("administrativeArea"), "postal_code": addr.get("postalCode"),
            "lat": _float(geo.get("lat")), "lon": _float(geo.get("long")),
            "classifications": [c.get("classification") for c in core.get("propertyClassifications") or [] if c.get("classification")],
            "state": core.get("state"), "visibility": core.get("accessVisibility"),
            "presented_by": (core.get("publication") or {}).get("presentedBy"),
            "captured": _capture_date(core),
            "modified": (core.get("modified") or "")[:10] or None,
            "floor_count": len(core.get("floors") or []) or None,
        },
        "insights_available": bool(ins),
        "insights_note": raw.get("insights_note"),
    }


def _float(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def room_matches(room: dict, terms: list[str]) -> bool:
    """Whole-word match of any term against the room's name (or classifier label + tags when unnamed)."""
    hay = " | ".join(_room_texts(room))
    return any(_has_word(hay, t) for t in terms)


def search(summary: dict, keyword: str) -> dict:
    """Whole-word search across room names/types, owner tags, labels, notes, measurements and detected objects.
    A room-type word (e.g. 'toilet') also finds rooms of that category."""
    k = keyword.lower().strip()
    cat = next((c for c, terms in ROOM_TYPES.items() if k in terms or k == c.replace("_", " ")), None)
    hit = lambda text: _has_word(text or "", k)  # noqa: E731
    return {
        "rooms": [r["label"] for r in summary["rooms"] if room_matches(r, [k]) or (cat and r.get("category") == cat)],
        "objects": [o for o in summary["objects"] if hit(o["label"])],
        "tags": [t for t in summary["tags"] if hit(f"{t['label']} {t['description']}")],
        "labels": [l for l in summary.get("labels") or [] if hit(l)],
        "notes": [n for n in summary.get("notes") or [] if hit(n)],
        "measurements": [m for m in summary.get("measurements") or [] if hit(m["label"])],
    }


# ---------------------------------------------------------------- interior facts (contract)

def _dedupe_openings(rooms: list[dict]) -> list[dict]:
    """A door between two rooms is listed on both boundaries with identical measurements: merge those pairs."""
    out: list[dict] = []
    for r in rooms:
        for o in r["openings"]:
            twin = next((d for d in out if d["_key"] == o["_key"] and len(d["rooms"]) == 1 and d["_room_id"] != r["id"]), None)
            if twin:
                twin["rooms"].append(r["label"])
            else:
                out.append({**o, "rooms": [r["label"]], "_room_id": r["id"]})
    return out


def interior_facts(summary: dict) -> dict:
    """Deterministic interior facts from a scan summary. A stable contract consumed by other agents and the
    engine; values are None when the scan can't tell."""
    rooms = summary["rooms"]
    tiers = summary.get("tiers_available") or (["core", "pi"] if summary.get("insights_available") else ["core"])
    notes: list[str] = []

    # ceilings
    def rep(r: dict) -> float | None:
        return r.get("ceiling_min_ft") or r.get("height_ft")

    measured = [r for r in rooms if rep(r)]
    room_area = sum(r["area_sqft"] or 0 for r in rooms)
    measured_area = sum(r["area_sqft"] or 0 for r in measured)
    unmeasured = sorted((r for r in rooms if not rep(r)), key=lambda r: -(r["area_sqft"] or 0))
    if measured:
        mins = [r.get("ceiling_min_ft") or r["height_ft"] for r in measured]
        maxs = [r.get("ceiling_max_ft") or r["height_ft"] for r in measured]
        ceiling = {"min_ft": min(mins), "max_ft": max(maxs), "median_ft": round(statistics.median(rep(r) for r in measured), 1)}
    else:
        ceiling = {"min_ft": None, "max_ft": None, "median_ft": None}
    ceiling["measured_area_share"] = round(measured_area / room_area, 2) if room_area else None
    ceiling["unmeasured_rooms"] = [{"label": r["label"], "area_sqft": r["area_sqft"]} for r in unmeasured[:5]]
    if measured and ceiling["measured_area_share"] is not None and ceiling["measured_area_share"] < 0.8 and unmeasured:
        big = unmeasured[0]
        notes.append(f"Ceiling height is measured in only {ceiling['measured_area_share']:.0%} of the floor area; "
                     f"the largest unmeasured room is {big['label']}" + (f" ({big['area_sqft']:,.0f} sq ft)" if big["area_sqft"] else "") + ".")

    # openings
    has_boundary = "boundary" in tiers
    openings = _dedupe_openings(rooms) if has_boundary else []
    doors = [o for o in openings if o["type"] in ("doorway", "opening")]
    windows = [o for o in openings if o["type"] == "window"]
    doorways = [{"room": " / ".join(o["rooms"]), "width_in": o["width_in"], "height_in": o["height_in"],
                 "kind": "open passage" if o["type"] == "opening" else DOOR_KINDS.get(o["label"] or "", o["label"] or "door")}
                for o in sorted(doors, key=lambda o: o["width_in"])]

    rooms_by_type = {t: sum(1 for r in rooms if r.get("category") == t) for t in ROOM_TYPES}
    if any(r.get("label_source") == "classifier" for r in rooms):
        notes.append("Unnamed rooms are typed by Matterport's residential room classifier (Bathroom, Bedroom, Hallway...); room names set by the scanner take precedence.")
    if summary.get("hidden_room_count"):
        notes.append(f"{summary['hidden_room_count']} non-area pseudo-room(s) (Void/Facade) were excluded.")
    if summary.get("insights_note"):
        notes.append(summary["insights_note"])
    if not summary["objects"]:
        notes.append("This scan has no detected objects (fixtures, equipment); visible items must be checked in the 3D tour.")

    return {
        "indoor_area_sqft": summary.get("total_indoor_area_sqft"),
        "indoor_area_with_walls_sqft": summary.get("total_indoor_area_with_walls_sqft"),
        "ceiling": ceiling,
        "rooms_by_type": rooms_by_type,
        "doorways": doorways,
        "narrowest_door_in": min((d["width_in"] for d in doorways), default=None),
        "wide_doors": sum(1 for d in doorways if d["width_in"] >= WIDE_DOOR_IN) if has_boundary else None,
        "windows": {
            "count": len(windows) if has_boundary else None,
            "total_width_ft": round(sum(w["width_in"] for w in windows) / 12, 1) if has_boundary else None,
            "rooms": sorted({rm for w in windows for rm in w["rooms"]}),
        },
        "owner_annotations": len(summary["tags"]) + len(summary.get("labels") or []) + len(summary.get("notes") or []) + len(summary.get("measurements") or []),
        "tiers_available": tiers,
        "objects_available": bool(summary["objects"]),
        "notes": notes,
    }
