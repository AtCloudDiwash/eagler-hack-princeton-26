"""Build the compact CoStar index the app uses for rentable area, available spaces, asking rents and building facts.

Reads the CoStar hackathon kit (licensed sponsor data; never committed) and writes
backend/fixtures/costar_index.json (gitignored). Run once:
    cd backend && .venv/bin/python scripts/build_costar_index.py [path/to/costar-hackathon-kit]
Default kit path: $COSTAR_KIT_DIR or ~/Downloads/costar-hackathon-kit.

Record keys (one per commercial property). Keys marked * are only written when known (sparse, to keep the file small).
  id, lat, lon, address, name, type          property identity (type = decoded PropertyType)
  rentable_sqft, rentable_basis               RBA (GLA for retail) and which one it is
  gross_sqft, typical_floor_sqft, stories     grossBuildingAreaSquareFeet, grossTypicalFloorSquareFeet, numStoriesAboveGrade
  lot_sqft, parking_ratio                     lotSize (+unit) in sq ft; parkingRatio (spaces per 1,000 sq ft)
  year_built                                  first constructionEvents[] eventType 2 (ConstructionComplete); null if none
  matterport_models                           Matterport model ids for the property (from commercial-properties.csv)
  matterport_scans                            [{"id", "caption"}] the same ids with the attachment caption ("Suite 100")
  lease_listings                              lease listings (below)
  * year_renovated        latest RenovationFinished / RedevelopmentComplete event or renovations[].endDate year
  * renovated_systems     improvement types from renovations[] (e.g. ["hvac", "roof", "lobby"])
  * building_class        buildingClass A/B/C/F
  * ceiling_height_ft     structural ceilingHeightFeet (+inches), max ceiling (mostly retail/industrial/flex)
  * slab_to_slab_ft       structural slabToSlabHeightFeet (office)
  * building_height_ft    buildingHeightInFeet
  * construction_material buildingConstructionMaterial (Masonry, Steel, WoodFrame, ...)
  * subtype               propertySubtype (e.g. Office_Medical, GeneralRetail_Restaurant)
  * parking_spaces        sum of parking[].totalSpaces;  * parking_types: parking[].parkingType names
  * elevators             passenger + freight elevators that exist (0 when all are recorded as absent)
  * has_elevator          true when a passenger/freight elevator exists, false when recorded absent
  * sprinklers            hasSprinklers (true/false; null = unknown, omitted);  * sprinkler_type: Wet/Dry/Esfr
  * zoning                zoningDescription, with "None"/"N/Ap"/"N/A" placeholders dropped
lease_listings[]: listing_id, status, total_available_sqft, min_divisible_sqft, max_contiguous_sqft, spaces
  * condition             listing buildingConditionRating (Poor, NeedsImprovement, Adequate, Good, Excellent)
  * note_flags            keyword flags from the listing-level notes (see NOTE_FLAGS)
spaces[] (on-market only): suite, floor, sqft_min, sqft_max, rate_low, rate_high, rate_basis, service, use,
                           lease_pending, available_on
  * space_type            Relet / New / Sublet / Assignment
  * cam_per_sqft_yr       commonAreaMaintenanceAmount normalized to $/sq ft/yr (monthly x12; implausible values dropped)
  * note_flags            keyword flags from the space notes: restaurant, dental, medical, restaurant_marketed,
                          second_generation, built_out, shell
  * note_snippet          <= 200 chars of the space note around the strongest keyword hit
  * prior_buildout        location-occupancy spaces[].buildOut of the same property + suite (RestaurantsAndCafes, Dental, ...)
  * buildout_status       ... buildOutStatus (RawSpace, ShellSpace, PartialBuildOut, FullBuildOut, SpecSuite)
  * buildout_condition    ... buildOutConditionType (NeedsRenovation, Average, Excellent, ...)
  * prior_tenant_current  true when that occupancy has no end date (the tenant may still be in place)
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "fixtures" / "costar_index.json"
SQFT_PER_ACRE = 43_560
MATTERPORT_REF_TYPES = {36, 234}  # MatterportScan, MatterportStreamingKey
ZONING_PLACEHOLDER = re.compile(r"^\s*(none|n/?ap?|na|n\.a\.)\s*(,.*)?$", re.I)
RENOVATION_SYSTEMS = {1: "bathrooms", 2: "building amenities", 3: "common areas", 4: "elevators", 5: "facade",
                      6: "hvac", 7: "lobby", 8: "roof", 9: "site", 10: "structural"}

# Keyword flags for listing/space notes, in priority order (the first hit picks the snippet).
NOTE_FLAGS: list[tuple[str, re.Pattern]] = [(k, re.compile(p, re.I)) for k, p in [
    # restaurant = evidence of an existing kitchen/restaurant build-out; restaurant_marketed = only marketed for restaurant use
    ("restaurant", r"(2nd|second)[- ]gen\w*\s+(restaurant|caf[eé]|kitchen)|former\s+(restaurant|caf[eé]|bakery|pizz\w*|deli|bar)\b"
                   r"|restaurant\s+(build[- ]?out|infrastructure|equipment)|\bhoods?\b"
                   r"|grease\s+(trap|interceptor)|walk[- ]in\s+(cooler|freezer)|commercial\s+kitchen|kitchen\s+equipment"),
    ("dental", r"dental\s+(office|suite|space|build|clinic|practice|use)|built[- ]out\s+dental|former\s+dent|\bdentist|operator(y|ies)\b"),
    ("medical", r"exam\s+rooms?|medical\s+(office|suite|space|build[- ]?out|clinic|use)|(2nd|second)[- ]gen\w*\s+medical"
                r"|former\s+(medical|doctor|clinic|physician)|\bclinic\b"),
    ("restaurant_marketed", r"restaurant\s+(space|ready|use|location)|ideal\s+for\s+(a\s+)?restaurant"),
    ("second_generation", r"(2nd|second)[- ]gen"),
    ("built_out", r"built[- ]out|move[- ]in[- ]ready|turn[- ]?key|plug[- ]and[- ]play"),
    ("shell", r"\b(gr[ae]y|cold|warm|vanilla)\s+shell\b|\bshell\s+(space|condition|building)\b"),
]]


def _enums(kit: Path) -> dict:
    return json.loads((kit / "schemas" / "enums.json").read_text())


def _rentable(r: dict) -> tuple[float | None, str | None]:
    if r.get("rentableBuildingAreaSquareFeet"):
        return r["rentableBuildingAreaSquareFeet"], "RBA"
    gla = (r.get("propertyRetail") or {}).get("grossLeasableAreaSquareFeet")
    if gla:
        return gla, "GLA"
    for k, v in r.items():
        if k.startswith("property") and isinstance(v, dict) and v.get("rentableBuildingAreaSquareFeet"):
            return v["rentableBuildingAreaSquareFeet"], "RBA"
    return None, None


def _floor(name: str | None) -> str | None:
    """'FirstFloor' -> 'First Floor'; unknown floors -> None."""
    if not name or name in {"Unknown", "UnknownFloor"}:
        return None
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name)


def _lot_sqft(r: dict) -> float | None:
    size, unit = r.get("lotSize"), r.get("lotSizeMeasurementType")
    if not size:
        return None
    return round(size * SQFT_PER_ACRE) if unit == 2 else round(size * 10.7639) if unit == 3 else round(size) if unit == 1 else None


def _enum(table: dict, code) -> str | None:
    """Decoded enum name, or None for missing/Unknown (code 0)."""
    if not code:
        return None
    name = table.get(str(code))
    return None if not name or name.startswith("Unknown") else name


def note_flags(texts: list[str]) -> tuple[list[str], str | None]:
    """Keyword flags found in the notes, and a short snippet around the highest-priority hit."""
    flags, snippet = [], None
    for flag, pat in NOTE_FLAGS:
        for t in texts:
            m = pat.search(t)
            if m:
                flags.append(flag)
                if snippet is None:
                    start = max(0, m.start() - 80)
                    snippet = ("…" if start else "") + " ".join(t[start:start + 200].split())
                break
    if snippet is None and texts:
        snippet = " ".join(texts[0][:160].split()) or None
    return flags, snippet


def _cam_per_year(s: dict) -> float | None:
    amt = s.get("commonAreaMaintenanceAmount")
    if not amt or amt <= 0:
        return None
    if s.get("rateBasis") == 1:  # monthly $/sf; larger values are flat monthly totals, not per-sf rates
        return round(amt * 12, 2) if amt <= 5 else None
    return round(amt, 2) if amt <= 60 else None


def _structural(r: dict) -> list[dict]:
    return [st for k in ("propertyOffice", "propertyRetail", "propertyIndustrial", "propertyFlex")
            if (st := (r.get(k) or {}).get("structural"))]


def year_built(r: dict) -> int | None:
    """Year of the first ConstructionComplete event (eventType 2); the kit has no yearBuilt field."""
    built = [e["year"] for e in r.get("constructionEvents") or [] if e.get("eventType") == 2 and e.get("year")]
    return min(built) if built else None


def building_fields(r: dict, enums: dict) -> dict:
    """The sparse building facts for one commercial-property record (only known values)."""
    out: dict = {}
    events = r.get("constructionEvents") or []
    reno_years = [e["year"] for e in events if e.get("eventType") in (4, 16) and e.get("year")]
    systems: set[str] = set()
    for rv in r.get("renovations") or []:
        if (rv.get("endDate") or "")[:4].isdigit():
            reno_years.append(int(rv["endDate"][:4]))
        systems.update(RENOVATION_SYSTEMS[t] for t in rv.get("renovationImprovementTypes") or [] if t in RENOVATION_SYSTEMS)
    if reno_years:
        out["year_renovated"] = max(reno_years)
    if systems:
        out["renovated_systems"] = sorted(systems)
    if cls := _enum(enums.get("BuildingClass", {}), r.get("buildingClass")):
        out["building_class"] = cls
    structural = _structural(r)
    ceil = [st["ceilingHeightFeet"] + (st.get("ceilingHeightInches") or 0) / 12 for st in structural if st.get("ceilingHeightFeet")]
    if ceil:
        out["ceiling_height_ft"] = round(max(ceil), 1)
    slab = [st["slabToSlabHeightFeet"] for st in structural if st.get("slabToSlabHeightFeet")]
    if slab:
        out["slab_to_slab_ft"] = max(slab)
    if r.get("buildingHeightInFeet"):
        out["building_height_ft"] = r["buildingHeightInFeet"]
    if mat := _enum(enums.get("BuildingConstructionMaterialType", {}), r.get("buildingConstructionMaterial")):
        out["construction_material"] = mat
    if sub := _enum(enums.get("PropertySubtype", {}), r.get("propertySubtype")):
        out["subtype"] = sub
    parking = r.get("parking") or []
    spaces = [p["totalSpaces"] for p in parking if p.get("totalSpaces")]
    if spaces:
        out["parking_spaces"] = sum(spaces)
    ptypes = sorted({n for p in parking if (n := _enum(enums.get("ParkingType", {}), p.get("parkingType")))})
    if ptypes:
        out["parking_types"] = ptypes
    elev = [e for st in structural for e in st.get("elevators") or [] if e.get("elevatorType") in (1, 2)]
    if any(e.get("elevatorState") == 1 for e in elev):
        out["has_elevator"] = True
        counts = [e["numElevators"] for e in elev if e.get("elevatorState") == 1 and e.get("numElevators")]
        if counts:
            out["elevators"] = sum(counts)
    elif elev and all(e.get("elevatorState") == 2 for e in elev):
        out["has_elevator"], out["elevators"] = False, 0
    if r.get("hasSprinklers") is not None:
        out["sprinklers"] = bool(r["hasSprinklers"])
    if st := _enum(enums.get("SprinklerType", {}), r.get("sprinklerType")):
        out["sprinkler_type"] = st
    z = (r.get("zoningDescription") or "").strip()
    if z and not ZONING_PLACEHOLDER.match(z):
        out["zoning"] = z
    return out


def _occupancy_buildouts(kit: Path, enums: dict) -> dict[tuple[str, str], dict]:
    """(propertyId, suite) -> the most recent occupied-space build-out recorded for that suite."""
    bo, status, cond = enums.get("BuildOut", {}), enums.get("BuildOutStatus", {}), enums.get("BuildOutConditionType", {})
    best: dict[tuple[str, str], tuple[str, dict]] = {}
    with open(kit / "data" / "location-occupancy.jsonl") as f:
        for line in f:
            r = json.loads(line)
            current = r.get("toDate") is None
            when = "9999" if current else (r.get("toDate") or "")
            for s in r.get("spaces") or []:
                suite = (s.get("suite") or "").strip().lower()
                info = {k: v for k, v in {
                    "prior_buildout": _enum(bo, s.get("buildOut")), "buildout_status": _enum(status, s.get("buildOutStatus")),
                    "buildout_condition": _enum(cond, s.get("buildOutConditionType"))}.items() if v}
                if not suite or not info:
                    continue
                if current:
                    info["prior_tenant_current"] = True
                key = (str(r["propertyId"]), suite)
                if key not in best or when > best[key][0]:
                    best[key] = (when, info)
    return {k: v for k, (_, v) in best.items()}


def _matterport_captions(r: dict) -> dict[str, str]:
    """Matterport model id -> caption, from the property's attachments (and apartment model/unit attachments)."""
    atts = list(r.get("attachments") or [])
    apt = r.get("propertyApartment") or {}
    for m in apt.get("models") or []:
        atts += m.get("attachments") or []
        for u in m.get("units") or []:
            atts += u.get("attachments") or []
    for u in apt.get("units") or []:
        atts += u.get("attachments") or []
    caps: dict[str, str] = {}
    for a in atts:
        key = a.get("videoKey")
        if key and a.get("videoExternalReferenceType") in MATTERPORT_REF_TYPES and a.get("caption") and key not in caps:
            caps[key] = " ".join(a["caption"].split())[:80]
    return caps


def main() -> None:
    kit = Path(sys.argv[1] if len(sys.argv) > 1 else os.getenv("COSTAR_KIT_DIR") or Path.home() / "Downloads" / "costar-hackathon-kit").expanduser()
    if not (kit / "data" / "commercial-property.jsonl").exists():
        sys.exit(f"CoStar kit not found at {kit}. Pass its path as the first argument.")
    enums = _enums(kit)
    ptype, service, use = enums.get("PropertyType", {}), enums.get("ServiceType", {}), enums.get("SpaceUse", {})
    floors = enums.get("FloorName", {})  # floorName is an enum code (24 = FirstFloor), not a floor number
    space_types, conditions = enums.get("SpaceType", {}), enums.get("BuildingConditionRating", {})
    buildouts = _occupancy_buildouts(kit, enums)

    models: dict[str, list[str]] = defaultdict(list)
    with open(kit / "commercial-properties.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("MatterportModelId"):
                models[row["PropertyId"]].append(row["MatterportModelId"])

    listing_captions: dict[str, dict[str, str]] = defaultdict(dict)
    listings: dict[str, list[dict]] = defaultdict(list)
    with open(kit / "data" / "commercial-listing-summary.jsonl") as f:
        for line in f:
            r = json.loads(line)
            for a in r.get("attachments") or []:
                if a.get("videoKey") and a.get("videoExternalReferenceType") in MATTERPORT_REF_TYPES and a.get("caption"):
                    listing_captions[str(r.get("propertyId"))].setdefault(a["videoKey"], " ".join(a["caption"].split())[:80])
            fl = r.get("forLeaseSummary")
            if not fl:
                continue
            spaces_by_prop: dict[str, list[dict]] = defaultdict(list)
            for s in fl.get("spaces") or []:
                if s.get("dateOffMarket"):
                    continue  # no longer on the market
                pid = str(s.get("propertyId") or r.get("propertyId"))
                space = {
                    "suite": s.get("suite"), "floor": _floor(floors.get(str(s.get("floorName")))),
                    "sqft_min": s.get("squareFeetMin"), "sqft_max": s.get("squareFeetMax"),
                    "rate_low": s.get("rateLow") or None, "rate_high": s.get("rateHigh") or None,
                    "rate_basis": {1: "monthly", 2: "yearly"}.get(s.get("rateBasis")),
                    "service": service.get(str(s.get("serviceType"))), "use": use.get(str(s.get("spaceUse"))),
                    "lease_pending": bool(s.get("isLeasePending")), "available_on": (s.get("availableOnDate") or "")[:10] or None,
                }
                flags, snippet = note_flags([n["value"] for n in s.get("notes") or [] if n.get("value")])
                extra = {"space_type": _enum(space_types, s.get("spaceType")), "cam_per_sqft_yr": _cam_per_year(s),
                         "note_flags": flags or None, "note_snippet": snippet,
                         **buildouts.get((pid, (s.get("suite") or "").strip().lower()), {})}
                space.update({k: v for k, v in extra.items() if v is not None})
                spaces_by_prop[pid].append(space)
            lflags, _ = note_flags([n["value"] for n in r.get("notes") or [] if n.get("value")])
            for pid, spaces in spaces_by_prop.items():
                listing = {
                    "listing_id": r["id"], "status": r.get("listingStatus"),
                    "total_available_sqft": fl.get("totalAvailableSquareFeet"),
                    "min_divisible_sqft": fl.get("minDivisibleSquareFeet"), "max_contiguous_sqft": fl.get("maxContiguousSquareFeet"),
                    "spaces": spaces,
                }
                if cond := _enum(conditions, r.get("buildingConditionRating")):
                    listing["condition"] = cond
                if lflags:
                    listing["note_flags"] = lflags
                listings[pid].append(listing)

    out = []
    with open(kit / "data" / "commercial-property.jsonl") as f:
        for line in f:
            r = json.loads(line)
            a = r.get("primaryAddress") or {}
            if a.get("latitude") is None or a.get("longitude") is None:
                continue
            rentable, basis = _rentable(r)
            pid = str(r["id"])
            caps = {**listing_captions.get(pid, {}), **_matterport_captions(r)}
            ids = models.get(pid, [])
            out.append({
                "id": r["id"], "lat": a["latitude"], "lon": a["longitude"],
                "address": ", ".join(x for x in [" ".join(str(p) for p in [a.get("streetNumber"), a.get("streetName"), a.get("streetType")] if p), a.get("city"), a.get("state")] if x),
                "name": r.get("buildingName"), "type": ptype.get(str(r.get("propertyType"))),
                "rentable_sqft": rentable, "rentable_basis": basis,
                "gross_sqft": r.get("grossBuildingAreaSquareFeet"), "typical_floor_sqft": r.get("grossTypicalFloorSquareFeet"),
                "stories": r.get("numStoriesAboveGrade"), "lot_sqft": _lot_sqft(r), "year_built": year_built(r),
                "parking_ratio": r.get("parkingRatio"),
                "matterport_models": ids, "matterport_scans": [{"id": m, "caption": caps.get(m)} for m in dict.fromkeys(ids)],
                "lease_listings": listings.get(pid, []),
                **building_fields(r, enums),
            })
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"source": "CoStar hackathon kit (licensed; do not commit)", "properties": out}, separators=(",", ":")))
    n = len(out)
    with_rentable = sum(1 for p in out if p["rentable_sqft"])
    with_spaces = sum(1 for p in out if any(l["spaces"] for l in p["lease_listings"]))
    print(f"Saved {n} properties ({with_rentable} with rentable area, {with_spaces} with spaces on the market) to {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
    keys = ["year_built", "year_renovated", "renovated_systems", "building_class", "ceiling_height_ft", "slab_to_slab_ft", "building_height_ft",
            "construction_material", "subtype", "parking_spaces", "elevators", "has_elevator", "sprinklers", "zoning"]
    print("Coverage: " + ", ".join(f"{k} {sum(1 for p in out if p.get(k) is not None)}" for k in keys))
    spaces = [s for p in out for l in p["lease_listings"] for s in l["spaces"]]
    skeys = ["space_type", "cam_per_sqft_yr", "note_flags", "note_snippet", "prior_buildout", "buildout_status"]
    print(f"Spaces {len(spaces)}: " + ", ".join(f"{k} {sum(1 for s in spaces if s.get(k) is not None)}" for k in skeys)
          + f"; captioned scans {sum(1 for p in out for m in p['matterport_scans'] if m['caption'])}/{sum(len(p['matterport_scans']) for p in out)}")


if __name__ == "__main__":
    main()
