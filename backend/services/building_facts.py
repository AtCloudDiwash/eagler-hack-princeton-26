"""Building facts: one typed, sourced view of what is known about a building, merged from CoStar and Vexcel.

    facts(prop, feature) -> {"facts": {fact_id: Fact}, "costar_id": str | None, "sources": [str]}
    Fact = {"value": ..., "unit": str | None, "source": "CoStar" | "Vexcel" | "OpenStreetMap",
            "confidence": "high" | "medium" | "low", "note": str | None}

`prop` is a property/candidate dict (needs "lat"/"lon"; uses "footprint", "best_space", "area_sqft", "stories_est",
"roof_condition", "source" when present). `feature` is the raw Vexcel feature (or None). The CoStar record is found
with services.costar.match, the same way discovery and the property detail do.

Rules:
  - Unknown facts are omitted; a fact's value is never None.
  - CoStar (recorded by researchers) wins over Vexcel (inferred from aerial imagery). When both exist and disagree,
    the CoStar value is kept and the Vexcel reading goes into "note".
  - No network and no exceptions on missing data: a missing index, feature or field just yields fewer facts.

Fact ids: year_built, last_renovation_year, renovated_systems, building_class, condition_rating, ceiling_height_ft,
stories, building_height_ft, elevators, sprinklers, zoning_code, parking_spaces, parking_ratio_per_1000,
construction_material, property_subtype, second_generation_use, prior_buildout_status, cam_per_sqft_yr, gross_sqft,
typical_floor_sqft, available_sqft, footprint_sqft, paved_area_sqft, roof_condition, rooftop_ac_units, stories_estimate.
"""
from __future__ import annotations

import logging
from statistics import median
from typing import Any

from config import roof_condition_labels
from services import costar
from services.vexcel import primary_structure, stories_estimate

log = logging.getLogger("turnkey.building_facts")

SQFT_PER_PARKING_SPACE = 325  # stall + aisle share (same assumption as services/program.py)
FT_STRUCTURE_PER_FLOOR = 3  # slab, ducts and ceiling between a floor's height and its clear height
_RANK = {"high": 3, "medium": 2, "low": 1}

_BUILDOUT_USE = {"RestaurantsAndCafes": "restaurant", "FastFood": "restaurant", "QuickService": "restaurant", "BarOrNightclub": "restaurant",
                 "Dental": "dental", "StandardMedical": "medical", "Healthcare": "medical", "PhysicalTherapy": "medical"}
_BUILDOUT_STATUS = {"RawSpace": "shell", "ShellSpace": "shell", "PartialBuildOut": "partial", "FullBuildOut": "full", "SpecSuite": "full"}
_SUBTYPE_USE = {"GeneralRetail_Restaurant": "restaurant", "GeneralRetail_FastFood": "restaurant", "GeneralRetail_QuickService": "restaurant",
                "GeneralRetail_Bar": "restaurant", "Flex_Cafe": "restaurant", "Office_Medical": "medical"}
_FLAG_USES = ("restaurant", "dental", "medical")  # note flags that name a prior use, most specific first
_CONDITION = {"Poor": "poor", "NeedsImprovement": "needs_improvement", "Adequate": "adequate", "Good": "good", "Excellent": "excellent"}


def fact_value(f: dict, fact_id: str, default: Any = None) -> Any:
    """The value of one fact from a facts() result (or its "facts" table), else default."""
    table = f.get("facts", f) if isinstance(f, dict) else {}
    fact = table.get(fact_id) if isinstance(table, dict) else None
    return fact["value"] if isinstance(fact, dict) and "value" in fact else default


def facts(prop: dict, feature: dict | None) -> dict:
    """Everything known about the building, one entry per fact id (see module docstring)."""
    prop = prop or {}
    rec = _costar_record(prop)
    out: dict[str, dict] = {}
    if rec:
        _costar_facts(out, rec, prop)
    _vexcel_facts(out, prop, feature)
    sources = list(dict.fromkeys(f["source"] for f in out.values()))
    return {"facts": out, "costar_id": str(rec["id"]) if rec else None, "sources": sources}


# ---------------------------------------------------------------- helpers

def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _put(out: dict, fid: str, value: Any, unit: str | None, source: str, confidence: str, note: str | None = None) -> None:
    """Record a fact unless it is unknown or already known from a better source (first writer wins)."""
    if value is None or value == "" or value == [] or fid in out:
        return
    out[fid] = {"value": value, "unit": unit, "source": source, "confidence": confidence, "note": note}


def _add_note(out: dict, fid: str, note: str) -> None:
    if fid in out:
        out[fid]["note"] = f"{out[fid]['note']}; {note}" if out[fid]["note"] else note


def _costar_record(prop: dict) -> dict | None:
    lat, lon = _num(prop.get("lat")), _num(prop.get("lon"))
    if lat is None or lon is None:
        return None
    try:
        return costar.match(lat, lon, prop.get("footprint"))
    except Exception as err:  # noqa: BLE001 - a bad footprint or index must not break the caller
        log.warning("CoStar match failed: %s", err)
        return None


def _suite(s: dict) -> str:
    return f"Suite {s['suite']}" if s.get("suite") else "the listed space"


def _space_sqft(s: dict) -> float | None:
    return _num(s.get("sqft_max")) or _num(s.get("sqft_min"))


def _spaces(rec: dict, prop: dict) -> tuple[list[tuple[dict, dict]], bool]:
    """The (listing, space) pairs that describe the user's space, and whether it is one identified space.
    The candidate's best_space when it can be found in the record; else the only space; else all on-market spaces."""
    pairs = [(l, s) for l in rec.get("lease_listings") or [] for s in l.get("spaces") or []]
    best = prop.get("best_space") or {}
    if best:
        want_suite = str(best.get("suite") or "").strip().lower()
        want_sqft = _num(best.get("sqft"))
        for l, s in pairs:
            if str(s.get("suite") or "").strip().lower() == want_suite and (want_sqft is None or want_sqft in (_num(s.get("sqft_max")), _num(s.get("sqft_min")))):
                return [(l, s)], True
    open_pairs = [(l, s) for l, s in pairs if not s.get("lease_pending")]
    if len(open_pairs) == 1:
        return open_pairs, True
    return open_pairs, False


# ---------------------------------------------------------------- CoStar

def _costar_facts(out: dict, rec: dict, prop: dict) -> None:
    C = "CoStar"
    _put(out, "year_built", rec.get("year_built"), None, C, "high", "Year construction completed (CoStar)")
    _put(out, "last_renovation_year", rec.get("year_renovated"), None, C, "high", "Latest renovation/redevelopment completed (CoStar)")
    _put(out, "renovated_systems", rec.get("renovated_systems"), None, C, "high", "Systems upgraded in recorded renovations")
    _put(out, "building_class", rec.get("building_class"), None, C, "high", "Market-relative grade: A above average, B average, C below average")
    _put(out, "gross_sqft", _num(rec.get("gross_sqft")), "sq ft", C, "high", "Gross building area (whole building, all floors)")
    _put(out, "typical_floor_sqft", _num(rec.get("typical_floor_sqft")), "sq ft", C, "high", None)
    _put(out, "stories", rec.get("stories") or None, None, C, "high", "Stories above grade")
    _put(out, "building_height_ft", _num(rec.get("building_height_ft")), "ft", C, "high", None)
    _put(out, "construction_material", rec.get("construction_material"), None, C, "medium", "Predominant structure, from broker/marketing material")
    _put(out, "property_subtype", rec.get("subtype"), None, C, "high", None)
    _put(out, "parking_ratio_per_1000", _num(rec.get("parking_ratio")), "spaces per 1,000 sq ft", C, "high", None)
    if rec.get("parking_spaces"):
        types = rec.get("parking_types") or []
        _put(out, "parking_spaces", int(rec["parking_spaces"]), "spaces", C, "high", f"Parking: {', '.join(types).lower()}" if types else None)
    if rec.get("sprinklers") is not None:
        _put(out, "sprinklers", bool(rec["sprinklers"]), None, C, "high", f"{rec['sprinkler_type']} system" if rec.get("sprinkler_type") else None)
    if isinstance(rec.get("elevators"), int):
        _put(out, "elevators", rec["elevators"], "elevators", C, "high", "Passenger and freight elevators" if rec["elevators"] else "Recorded as having no elevator")
    elif rec.get("has_elevator"):
        _put(out, "elevators", 1, "elevators", C, "low", "At least one passenger/freight elevator recorded; count unknown")
    if z := rec.get("zoning"):
        code = z.split(",")[0].strip()
        _put(out, "zoning_code", code, None, C, "medium", f"CoStar zoning '{z}'; confirm with the city" if code != z else "Confirm with the city's zoning map")
    if _num(rec.get("ceiling_height_ft")):
        _put(out, "ceiling_height_ft", rec["ceiling_height_ft"], "ft", C, "high", "Maximum ceiling height recorded by CoStar")
    elif _num(rec.get("slab_to_slab_ft")):
        _put(out, "ceiling_height_ft", rec["slab_to_slab_ft"] - FT_STRUCTURE_PER_FLOOR, "ft", C, "medium",
             f"Estimated clear height: CoStar slab-to-slab {rec['slab_to_slab_ft']:g} ft minus ~{FT_STRUCTURE_PER_FLOOR} ft of structure")

    pairs, identified = _spaces(rec, prop)
    _space_facts(out, rec, pairs, identified)


def _space_facts(out: dict, rec: dict, pairs: list[tuple[dict, dict]], identified: bool) -> None:
    C = "CoStar"
    one = identified and len(pairs) == 1
    if one:
        l, s = pairs[0]
        if sq := _space_sqft(s):
            _put(out, "available_sqft", sq, "sq ft", C, "high", f"{_suite(s)} on the market")
    elif pairs:
        total = sum(_space_sqft(s) or 0 for _, s in pairs)
        _put(out, "available_sqft", total or None, "sq ft", C, "medium", f"Total of {len(pairs)} spaces on the market (no single space chosen)")

    cams = [(s, s["cam_per_sqft_yr"]) for _, s in pairs if _num(s.get("cam_per_sqft_yr"))]
    if one and cams:
        _put(out, "cam_per_sqft_yr", cams[0][1], "$/sq ft/yr", C, "high", f"CAM charge listed for {_suite(cams[0][0])}")
    elif cams:
        _put(out, "cam_per_sqft_yr", round(median(c for _, c in cams), 2), "$/sq ft/yr", C, "medium", f"Median CAM of {len(cams)} listed spaces")

    listings = [l for l, _ in pairs] + list(rec.get("lease_listings") or [])
    if cond := next((l["condition"] for l in listings if l.get("condition") in _CONDITION), None):
        _put(out, "condition_rating", _CONDITION[cond], None, C, "medium", "Listing's building-condition rating (poor, needs_improvement, adequate, good, excellent)")

    # prior build-out of the space: occupancy records (same suite) beat listing notes, which beat the building subtype
    best_conf = "high" if one else "medium"
    evidence: list[tuple[str, str, str]] = []  # (use, confidence, note)
    for _, s in pairs:
        if use := _BUILDOUT_USE.get(s.get("prior_buildout")):
            tenant = " (that tenant may still be in place)" if s.get("prior_tenant_current") else ""
            evidence.append((use, best_conf, f"CoStar tenant records show a {s['prior_buildout']} build-out in {_suite(s)}{tenant}"))
    for _, s in pairs:
        if use := next((u for u in _FLAG_USES if u in (s.get("note_flags") or [])), None):
            evidence.append((use, "medium" if one else "low", f"Listing note for {_suite(s)}: \"{s.get('note_snippet') or ''}\""))
    for l in listings:
        if use := next((u for u in _FLAG_USES if u in (l.get("note_flags") or [])), None):
            evidence.append((use, "low", "Mentioned in the listing's building description"))
            break
    if use := _SUBTYPE_USE.get(rec.get("subtype")):
        evidence.append((use, "low", f"Building subtype {rec['subtype']}"))
    if evidence:
        use, conf, note = max(evidence, key=lambda e: _RANK[e[1]])  # stable: first of the best rank
        _put(out, "second_generation_use", use, None, C, conf, note)

    status: list[tuple[str, str, str]] = []
    for _, s in pairs:
        if st := _BUILDOUT_STATUS.get(s.get("buildout_status")):
            cond = f", condition {s['buildout_condition']}" if s.get("buildout_condition") else ""
            status.append((st, best_conf, f"CoStar build-out of {_suite(s)}: {s['buildout_status']}{cond}"))
    for _, s in pairs:
        flags = s.get("note_flags") or []
        if "shell" in flags or "built_out" in flags:
            status.append(("shell" if "shell" in flags else "full", "medium" if one else "low", f"Listing note for {_suite(s)}: \"{s.get('note_snippet') or ''}\""))
    if status:
        st, conf, note = max(status, key=lambda e: _RANK[e[1]])
        _put(out, "prior_buildout_status", st, None, C, conf, note)


# ---------------------------------------------------------------- Vexcel (and the candidate's own aerial fields)

def _vexcel_facts(out: dict, prop: dict, feature: dict | None) -> None:
    V = "Vexcel"
    s = (primary_structure(feature) or {}) if feature else {}
    parcel = (feature or {}).get("properties") or {}
    aerial_source = "OpenStreetMap" if prop.get("source") == "osm" else V

    footprint = _num(s.get("footprint.area"))
    if footprint:
        _put(out, "footprint_sqft", round(footprint), "sq ft", V, "high", "Building outline from above (about one floor); not the leasable space")
    elif _num(prop.get("area_sqft")) and prop.get("source") != "costar":
        _put(out, "footprint_sqft", round(prop["area_sqft"]), "sq ft", aerial_source, "medium", "Building outline from above (about one floor)")

    paved = _num(parcel.get("hardscapes.area"))
    _put(out, "paved_area_sqft", round(paved) if paved else None, "sq ft", V, "medium", "Paved area on the parcel (lots, drives, walks); not all paving is parking")

    cond = _num(s.get("roof-characteristics.condition")) or (_num(prop.get("roof_condition")) if prop.get("source") != "costar" else None)
    if cond:
        label = roof_condition_labels().get(int(cond))
        _put(out, "roof_condition", int(cond) if cond == int(cond) else round(cond, 1), "score 1-5", V, "medium",
             f"{label} (Vexcel AI scale: 1 Bad, 2 Poor, 3 Fair, 4 Good, 5 Great; whole roof)" if label else None)

    ac = s.get("roof-objects.ac-unit.count")
    if isinstance(ac, (int, float)) and not isinstance(ac, bool):
        _put(out, "rooftop_ac_units", int(ac), "units", V, "medium", "Detected in imagery; units can be hidden, ground-mounted or on another roof level")

    est = stories_estimate(s) if s else None
    if est is None and prop.get("source") not in ("costar", None) and isinstance(prop.get("stories_est"), int):
        est = prop["stories_est"]
    height = _num(s.get("roof-characteristics.height"))
    if est:
        basis = f"roof height {height:.0f} ft / ~13 ft per story" if height else "Vexcel stories below eave"
        _put(out, "stories_estimate", est, None, V, "low", f"Estimate from {basis}")

    # Vexcel fallbacks for facts CoStar didn't record; otherwise note the Vexcel reading when it disagrees
    if "stories" in out and est and est != out["stories"]["value"]:
        _add_note(out, "stories", f"Vexcel estimates ~{est} from roof height; CoStar record preferred")
    _put(out, "stories", est, None, V, "low", "Estimated from roof height (no CoStar record)")

    if height and height >= 8:
        if "building_height_ft" in out and abs(out["building_height_ft"]["value"] - height) > max(6, 0.2 * height):
            _add_note(out, "building_height_ft", f"Vexcel measures the roof at ~{height:.0f} ft; CoStar record preferred")
        _put(out, "building_height_ft", round(height, 1), "ft", V, "medium", "Roof height above ground from elevation data")
        floors = fact_value(out, "stories")
        if floors:
            clear = height / floors - FT_STRUCTURE_PER_FLOOR
            if clear > 0:
                _put(out, "ceiling_height_ft", round(clear, 1), "ft", V, "low",
                     f"Estimated clear height: {height:.0f} ft roof / {floors} floor(s) minus ~{FT_STRUCTURE_PER_FLOOR} ft")

    if paved:
        est_spaces = int(paved // SQFT_PER_PARKING_SPACE)
        if "parking_spaces" in out:
            have = out["parking_spaces"]["value"]
            if abs(have - est_spaces) > max(10, 0.5 * have):
                _add_note(out, "parking_spaces", f"Vexcel paved area would fit ~{est_spaces} spaces; CoStar record preferred")
        elif est_spaces:
            _put(out, "parking_spaces", est_spaces, "spaces", V, "low", f"Upper bound if all {paved:,.0f} sq ft of paving were parking (~{SQFT_PER_PARKING_SPACE} sq ft per space)")


# ---------------------------------------------------------------- property panel highlights

def _floor_label(floor: Any) -> str:
    """'First Floor' / 36 / 'Ground' -> '1st floor' / '36th floor' / 'ground floor'."""
    from services.scan_identity import floor_number

    text = str(floor).strip()
    if text.lower() in {"ground", "ground floor", "street", "plaza", "lobby"}:
        return "ground floor"
    n = floor_number(floor)
    if not n:
        return text.lower()
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} floor"


def _money(v: float) -> str:
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}".rstrip("0").rstrip(".")


def highlights(prop: dict, feature: dict | None) -> list[dict]:
    """The property panel's tiles: the SAME nine metrics, in the same order, for every building, so buildings can be
    compared side by side. [{"id", "label", "value", "hint", "source", "icon", "missing"}]. CoStar values are recorded;
    Vexcel values are aerial measurements; a missing value says why ("Not listed", "No aerial data"), never a bare dash."""
    prop = prop or {}
    known = facts(prop, feature)["facts"]
    s = (primary_structure(feature) or {}) if feature else {}
    best = prop.get("best_space") or {}

    def rec(fid: str) -> Any:  # recorded by CoStar only
        f = known.get(fid)
        return f["value"] if f and f.get("source") == "CoStar" else None

    def tile(id_: str, label: str, icon: str, value: str | None, hint: str, source: str, missing: str) -> dict:
        """Short headline in `value` (fits the card), the rest in `sub`: "Class A · 43 stories" -> "Class A" / "43 stories"."""
        if not value:
            return {"id": id_, "label": label, "value": "Unknown" if len(missing) > 11 else missing, "sub": missing.lower() if len(missing) > 11 else None,
                    "hint": hint, "source": "none", "icon": icon, "missing": True}
        sub = None
        if value.endswith(" (est.)"):
            value, sub = value[: -len(" (est.)")], "estimate"
        if " · " in value:
            value, rest = value.split(" · ", 1)
            sub = f"{rest}, {sub}" if sub else rest
        elif " + " in value:
            value, rest = value.split(" + ", 1)
            sub = f"+ {rest}"
        return {"id": id_, "label": label, "value": value, "sub": sub, "hint": hint, "source": source, "icon": icon, "missing": False}

    # 1. the space you'd lease
    space = f"{best['sqft']:,.0f} sq ft" + (f" · {_floor_label(best['floor'])}" if best.get("floor") else "") if best.get("sqft") else None
    where = f"Suite {best['suite']}" if best.get("suite") else "the listed space"
    # 2. what it costs
    rate = best.get("rent_per_sqft_yr")
    if rate and best.get("sqft"):
        rent, rent_hint = f"{_money(rate * best['sqft'] / 12)}/mo", f"{_money(rate)}/sq ft/yr {best.get('service') or ''} for {where} (base rent; NNN charges extra on triple-net leases)."
    elif prop.get("asking_rent_per_sqft_yr"):
        lo, hi = prop["asking_rent_per_sqft_yr"]
        rent, rent_hint = f"{_money(lo)}" + (f"–{_money(hi)}" if hi != lo else "") + "/sf/yr", "Asking rents across the building's listed spaces (CoStar)."
    else:
        rent, rent_hint = None, "Asking rent from the CoStar listing."
    # 3. building grade and height
    cls, stories = rec("building_class"), rec("stories")
    est_stories = prop.get("stories_est") or stories_estimate(s)
    building = " · ".join(x for x in (f"Class {cls}" if cls else None, f"{stories} stories" if stories else (f"~{est_stories} stories (est.)" if est_stories else None)) if x)
    # 4. age
    year, reno = rec("year_built"), rec("last_renovation_year")
    built = f"{year}" + (f" · reno {reno}" if reno and reno != year else "") if year else None
    # 5. parking
    spaces, ratio = rec("parking_spaces"), rec("parking_ratio_per_1000")
    paved = s.get("hardscapes.parcel") or (feature or {}).get("properties", {}).get("hardscapes.area")
    if spaces:
        parking, p_src, p_hint = f"{spaces:,} spaces", "CoStar", "Building parking recorded by CoStar (shared with other tenants)."
    elif ratio:
        parking, p_src, p_hint = f"{ratio}/1,000 sf", "CoStar", "Parking ratio recorded by CoStar (spaces per 1,000 sq ft)."
    elif isinstance(paved, (int, float)) and paved >= 325:
        parking, p_src, p_hint = f"~{int(paved // 325)} spaces (est.)", "Vexcel", "Paved area on the parcel ÷ ~325 sq ft per space (aerial estimate; not all paving is parking)."
    else:
        parking, p_src, p_hint = None, "none", "Parking spaces (CoStar) or paved area (Vexcel)."
    # 6. floor plate: how big one floor is (ground-floor uses care about this, not the whole tower)
    plate = rec("typical_floor_sqft")
    fp = s.get("footprint.area") or prop.get("area_sqft")
    if plate:
        floor_plate, f_src, f_hint = f"{plate:,.0f} sq ft", "CoStar", "Typical floor size recorded by CoStar."
    elif isinstance(fp, (int, float)):
        floor_plate, f_src, f_hint = f"{fp:,.0f} sq ft", "Vexcel", "Building footprint measured from aerial imagery (about one floor)."
    else:
        floor_plate, f_src, f_hint = None, "none", "Size of one floor (CoStar typical floor or aerial footprint)."
    # 7-8. physical condition from the air
    cond = s.get("roof-characteristics.condition.precise-value") or s.get("roof-characteristics.condition")
    roof = f"{roof_condition_labels().get(max(1, min(5, round(cond))), '')} {cond:.1f}/5" if isinstance(cond, (int, float)) else None
    ac = s.get("roof-objects.ac-unit.count")
    ac_text = f"{ac:.0f} unit{'s' if ac != 1 else ''}" if isinstance(ac, (int, float)) else None
    # 9. what kind of building it is (an apartment block with shop space is not an office tower)
    rec_c = costar.match(prop["lat"], prop["lon"], prop.get("footprint")) if prop.get("lat") is not None and prop.get("lon") is not None else None
    sub = (rec_c or {}).get("subtype") or ""
    ctype = (rec_c or {}).get("type")
    TYPE_LABELS = {"Multifamily": "Apartments", "Retail": "Retail", "Office": "Office", "Industrial": "Industrial", "Flex": "Flex", "Hospitality": "Hotel", "Healthcare": "Medical"}
    detail = sub.split("_", 1)[1].replace("_", " ").lower() if "_" in sub else ""
    if ctype:
        btype, t_src = TYPE_LABELS.get(ctype, ctype) + (f" · {detail}" if detail and detail not in TYPE_LABELS.get(ctype, ctype).lower() else ""), "CoStar"
        if ctype == "Multifamily" and str(best.get("use") or "").lower() == "retail":
            btype = "Apartments + retail"
    elif s.get("building-type.class") or prop.get("building_type"):
        btype, t_src = f"{str(s.get('building-type.class') or prop.get('building_type')).replace('_', ' ').capitalize()} (aerial)", "Vexcel"
    else:
        btype, t_src = None, "none"

    return [
        tile("space", "Space for lease", "space", space, f"{where.capitalize()}: the CoStar listing closest to your size.", "CoStar listing", "Not listed"),
        tile("rent", "Asking rent", "rent", rent, rent_hint, "CoStar listing", "Not listed"),
        tile("building", "Building", "building", building or None, "CoStar's market grade (A/B/C) and recorded stories; '(est.)' = roof height ÷ ~13 ft.", "CoStar" if (cls or stories) else "Vexcel", "Not recorded"),
        tile("year", "Built", "year", built, "Year built and latest renovation (CoStar). Before 1991 = pre-ADA: expect accessibility upgrades.", "CoStar", "Not recorded"),
        tile("parking", "Parking", "parking", parking, p_hint, p_src, "Not recorded"),
        tile("floor_plate", "Floor size", "floors", floor_plate, f_hint, f_src, "Not recorded"),
        tile("roof", "Roof", "roof", roof, "Roof condition scored from aerial imagery (Vexcel, 1 Bad – 5 Great).", "Vexcel", "No aerial data"),
        tile("ac", "Rooftop AC", "fan", ac_text, "Units detected in aerial imagery; some can be hidden or ground-mounted.", "Vexcel", "No aerial data"),
        tile("type", "Building type", "building", btype, "CoStar property type (recorded) or Vexcel's aerial classification.", t_src, "Not recorded"),
    ]
