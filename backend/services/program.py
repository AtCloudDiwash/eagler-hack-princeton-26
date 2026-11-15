"""Space program: what the user's request implies, and how a building measures up against it.

The request ("40-seat restaurant with 8 staff, must have parking, open within 4 months") is turned into
a deterministic, config-driven program:

- size: target / min / max sq ft from the counts that size this business (seats, operatories, class
  size, members, employees; business_types.yaml `program.drivers`) or the stated sq ft;
- occupancy: occupant load (area-based IBC factors, never below the people the user said will be there),
  the IBC occupancy group, and what that triggers: exits, restrooms, sprinklers (occupancy_codes.yaml);
- building: suitable building types, ground floor, minimum ceiling height, typical build-out time;
- needs: everything else the user asked for (needs.yaml), as must-haves or nice-to-haves, each routed
  to the agent that checks it.

`site_checks()` then compares a building's known facts (CoStar building record, Vexcel, OSM) with the program. Everything here is
planning-level and cites the model code; local amendments and the architect's code analysis decide.
"""
from __future__ import annotations

import math
import re
from datetime import date

from config import business, needs_registry, occupancy_codes
from schemas import Intent, Need
from services.vexcel import primary_structure, stories_estimate

DISCLAIMER = (
    "Planning estimates from the 2021 IBC/IPC model codes and typical space standards. Your city's adopted "
    "code, its amendments and an architect's code analysis decide the final requirements."
)
SQFT_PER_PARKING_SPACE = 325  # stall + aisle share, same assumption as services/rules.py
_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], 1)}
_SEASONS = {"spring": 4, "summer": 7, "fall": 10, "autumn": 10, "winter": 1}
_MUST_CUES = ("must", "need", "needs", "required", "require", "has to", "have to", "essential", "non-negotiable", "a must", "only if", "no ")
_NICE_CUES = ("ideally", "prefer", "preferably", "nice to have", "would like", "bonus", "if possible", "hopefully", "plus")


# ---------------------------------------------------------------- parsing the request

def _kw_pattern(kw: str) -> str:
    return r"(?<![a-z0-9])" + re.escape(kw.lower()).replace(r"\ ", r"[\s-]+") + r"(?![a-z0-9])"


def parse_counts(query: str, business_type: str) -> dict[str, int]:
    """Counts stated for this business's sizing drivers ("40 seats", "team of 12", "4 operatories") plus staff."""
    q = query.lower().replace(",", "")
    out: dict[str, int] = {}
    drivers = business(business_type)["program"]["drivers"]
    for d in drivers:
        for kw in sorted(d["keywords"], key=len, reverse=True):
            pat = _kw_pattern(kw.removesuffix(" of"))
            m = re.search(rf"(\d{{1,5}})\s*(?:-|\s)?\s*{pat}", q) or re.search(rf"{pat}\s+(?:of\s+|for\s+)?(\d{{1,5}})(?!\s*(?:sq|sf|ft|%|k\b|\$))", q)
            if m and int(m.group(1)) > 0:
                out[d["field"]] = int(m.group(1))
                break
    driver_words = {kw for d in drivers for kw in d["keywords"]}
    if "staff" not in driver_words:
        m = re.search(r"(\d{1,4})\s*(?:-|\s)?\s*(?:staff|employees|workers|team members|cooks|servers|crew)\b", q) or re.search(r"\b(?:staff|team|crew)\s+of\s+(\d{1,4})", q)
        if m:
            out["staff"] = int(m.group(1))
    return out


def _priority(query: str, start: int) -> str:
    clause = re.split(r"[.;!?]|\bbut\b", query[max(0, start - 60):start].lower())[-1]
    if any(c in clause for c in _NICE_CUES):
        return "nice"
    if any(re.search(rf"\b{re.escape(c.strip())}\b", clause) for c in _MUST_CUES):
        return "must"
    return "nice"


def parse_needs(query: str) -> list[Need]:
    """Needs from config/needs.yaml found in the query, each marked must-have or nice-to-have."""
    q = query.lower()
    found: dict[str, Need] = {}
    for nid, cfg in needs_registry().items():
        for kw in sorted(cfg["keywords"], key=len, reverse=True):
            m = re.search(_kw_pattern(kw), q)
            if m:
                found[nid] = Need(id=nid, label=cfg["label"], priority=_priority(query, m.start()))
                break
    return list(found.values())


def parse_timeline(query: str, today: date | None = None) -> int | None:
    """Months until the user wants to open ("within 3 months", "in 6 weeks", "by March", "asap")."""
    q = query.lower()
    today = today or date.today()
    if m := re.search(r"(?:within|in|next|under)\s+(\d{1,2})\s*(month|week)s?", q):
        n = int(m.group(1))
        return n if m.group(2) == "month" else max(1, math.ceil(n / 4.3))
    if re.search(r"\b(asap|as soon as possible|immediately|right away|urgent)\b", q):
        return 2
    if m := re.search(r"\b(?:by|before|open in|opening in|launch in)\s+(?:early\s+|late\s+|mid\s+)?(" + "|".join([*_MONTHS, *_SEASONS]) + r")\b", q):
        target = _MONTHS.get(m.group(1)) or _SEASONS[m.group(1)]
        months = (target - today.month) % 12
        return months or 12
    if re.search(r"\bnext year\b", q):
        return 12 - today.month + 6
    return None


def parse_tenure(query: str) -> str:
    return "buy" if re.search(r"\b(buy|purchase|own the building|ownership|for sale)\b", query.lower()) else "lease"


# ---------------------------------------------------------------- the program

def _fixtures(occupant_load: int, group: dict) -> dict:
    """Minimum water closets and lavatories (IPC Table 2902.1), per sex then total."""
    per_sex = math.ceil(occupant_load / 2)

    def count(tiers: list) -> int:
        total, prev = 0, 0
        for up_to, per in tiers:
            chunk = min(per_sex, up_to or per_sex) - prev
            if chunk > 0:
                total += math.ceil(chunk / per)
            prev = up_to or per_sex
            if prev >= per_sex:
                break
        return max(total, 1)

    fx = group["fixtures"]
    wc = fx["water_closets"]
    men = count(wc.get("men") or wc["tiers"])
    women = count(wc.get("women") or wc["tiers"])
    lav = count(fx["lavatories"]["tiers"]) * 2
    unisex = occupant_load <= group["unisex_max_load"]
    return {
        "water_closets": 1 if unisex else men + women,
        "water_closets_men": None if unisex else men,
        "water_closets_women": None if unisex else women,
        "lavatories": 1 if unisex else lav,
        "drinking_fountains": max(1, math.ceil(occupant_load / fx["drinking_fountains_per"])) if occupant_load > 15 else 0,
        "service_sink": bool(fx.get("service_sink")),
        "single_restroom_allowed": unisex,
        "citation": wc["citation"],
    }


def target_size(intent: Intent) -> tuple[int, int, int, list[str]]:
    """(target, min, max sq ft, explanation lines)."""
    cfg = business(intent.business_type)
    sizing, drivers = cfg["sizing"], cfg["program"]["drivers"]
    counts = {**intent.occupancy, **({"seats": intent.seats} if intent.seats and "seats" not in intent.occupancy else {})}
    basis: list[str] = []
    driven = None
    for d in drivers:
        if counts.get(d["field"]):
            n = counts[d["field"]]
            driven = d["base_sqft"] + n * d["sqft_each"]
            line = f"{n} {d['label']} × {d['sqft_each']} sq ft" + (f" + {d['base_sqft']:,} sq ft support space" if d["base_sqft"] else "") + f" ≈ {driven:,} sq ft ({d['why']})"
            basis.append(line)
            break
    if intent.sqft:
        target = intent.sqft
        basis.insert(0, f"{intent.sqft:,} sq ft requested")
        if driven and abs(driven - intent.sqft) / intent.sqft > 0.25:
            basis.append(f"Note: your headcount suggests ~{driven:,} sq ft, {'more' if driven > intent.sqft else 'less'} than the {intent.sqft:,} sq ft requested.")
    elif driven:
        target = driven
    elif sizing.get("default_seats") and sizing.get("sqft_per_seat"):
        target = sizing["default_seats"] * sizing["sqft_per_seat"]
        basis.append(f"No size given: typical {sizing['default_seats']}-seat {cfg['label'].lower()} ({sizing['sqft_per_seat']} sq ft/seat)")
    else:
        target = sizing.get("default_sqft", 2500)
        basis.append(f"No size given: typical {cfg['label'].lower()} (~{target:,} sq ft)")
    return int(target), int(round(target * 0.85, -1)), int(round(target * 1.3, -1)), basis


def build(intent: Intent) -> dict:
    cfg = business(intent.business_type)
    prog = cfg["program"]
    codes = occupancy_codes()
    cites = codes["_citations"]
    target, lo, hi, size_basis = target_size(intent)
    counts = {**intent.occupancy, **({"seats": intent.seats} if intent.seats and "seats" not in intent.occupancy else {})}

    # occupant load: area method (IBC Table 1004.5), never below the people the user expects
    area_load, load_basis = 0, []
    for lf in prog["occupancy"]["load_factors"]:
        n = math.ceil(target * lf["share"] / lf["sqft_per_person"])
        area_load += n
        load_basis.append(f"{lf['label']}: {target * lf['share']:,.0f} sq ft ÷ {lf['sqft_per_person']} sq ft/person = {n}")
    people_each = {"seats": 1, "chairs": 3, "class_size": 1, "employees": 1, "members": 0}
    people = sum(counts.get(f, 0) * k for f, k in people_each.items()) + counts.get("staff", 0)
    occupant_load = max(area_load, people)
    if people > area_load:
        load_basis.append(f"You expect ~{people} people at once, more than the area method, so we use {people}")

    group_key = prog["occupancy"]["group"]
    small = prog["occupancy"].get("small_group")
    group_note = None
    if small and occupant_load < 50:
        group_note = f"Under 50 occupants, this assembly use is classified Group {small} ({cites['small_assembly']})."
        group_key = small
    group = codes[group_key]

    exits = 1 if occupant_load <= group["single_exit_max_load"] else 2 if occupant_load <= 500 else 3 if occupant_load <= 1000 else 4
    fx = _fixtures(occupant_load, group)
    spr = group["sprinklers"]
    spr_reasons = []
    if spr.get("fire_area_over_sqft") and target > spr["fire_area_over_sqft"]:
        spr_reasons.append(f"floor area over {spr['fire_area_over_sqft']:,} sq ft")
    if spr.get("occupant_load_at_least") and occupant_load >= spr["occupant_load_at_least"]:
        spr_reasons.append(f"{spr['occupant_load_at_least']}+ occupants")

    rest = f"{fx['water_closets']} toilet{'s' if fx['water_closets'] > 1 else ''}" + (" (one all-gender restroom is allowed)" if fx["single_restroom_allowed"] else f" ({fx['water_closets_men']} men's, {fx['water_closets_women']} women's)") + f", {fx['lavatories']} sink{'s' if fx['lavatories'] > 1 else ''}"
    code = [
        {"id": "occupancy_group", "rule": "Occupancy classification", "value": f"Group {group_key}", "detail": f"{group['label']}, ~{occupant_load} occupants." + (f" {group_note}" if group_note else ""), "citation": cites["small_assembly"] if group_note else cites["occupant_load"]},
        {"id": "exits", "rule": "Exits", "value": f"{exits} exit{'s' if exits > 1 else ''}", "detail": f"{occupant_load} occupants: " + ("one exit is enough (49 or fewer)." if exits == 1 else f"needs {exits} separate exits; one front door is not enough."), "citation": cites["exits"]},
        {"id": "restrooms", "rule": "Restrooms", "value": rest, "required_count": fx["water_closets"], "detail": f"Minimum plumbing fixtures for ~{occupant_load} occupants" + (" plus a service (mop) sink." if fx["service_sink"] else ".") + (f" {fx['drinking_fountains']} drinking fountain(s); a water dispenser often substitutes for restaurants." if fx["drinking_fountains"] else ""), "citation": fx["citation"]},
        {"id": "sprinklers", "rule": "Fire sprinklers", "value": "Likely required" if spr_reasons else "Not triggered by this use", "detail": (f"Triggered by {' and '.join(spr_reasons)}. Confirm the building has (or can add) a sprinkler system." if spr_reasons else spr.get("note") or "Below this occupancy's sprinkler thresholds; the building itself may still be sprinklered."), "citation": spr["citation"]},
    ]
    public = intent.business_type != "office"
    if public:
        code.append({"id": "accessible_route", "rule": "Accessibility", "value": "Accessible entrance, route and restroom", "detail": "Public-facing spaces need a step-free entrance, an accessible route and at least one accessible restroom; upper floors need an elevator.", "citation": cites["accessible_route"]})

    registry = needs_registry()
    needs = [{"id": n.id, "label": n.label, "priority": n.priority, "owner": registry[n.id]["owner"], "check": registry[n.id].get("check"), "triggers": " ".join(registry[n.id]["triggers"].split())} for n in intent.needs if n.id in registry]
    for n in needs:
        if n["id"] in {"alcohol", "live_music", "xray"}:
            code.append({"id": f"need_{n['id']}", "rule": n["label"], "value": "Extra approvals", "detail": n["triggers"], "citation": None})

    bm = prog["buildout_months"]
    timeline = None
    if intent.open_within_months:
        m = intent.open_within_months
        status = "risk" if m < bm[0] else "tight" if m < bm[1] else "ok"
        timeline = {"open_within_months": m, "buildout_months": bm, "status": status,
                    "detail": f"You want to open in ~{m} months; a typical {cfg['label'].lower()} build-out takes {bm[0]}-{bm[1]} months after signing" + {"risk": ", so you'll need a move-in-ready (second-generation) space.", "tight": ", which is tight: favour spaces that need little work.", "ok": ", which leaves room for a normal build-out."}[status]}

    acknowledged = [{"label": cfg["label"], "value": "business type", "source": "stated"}]
    labels = {d["field"]: d["label"] for d in prog["drivers"]} | {"staff": "staff", "seats": "seats"}
    for f, n in counts.items():
        acknowledged.append({"label": f"{n} {labels.get(f, f)}", "value": f, "source": "stated"})
    acknowledged.append({"label": f"~{target:,} sq ft", "value": "size", "source": "stated" if intent.sqft else "derived" if counts else "default"})
    acknowledged.append({"label": f"~{occupant_load} occupants · Group {group_key}", "value": "occupancy", "source": "derived"})
    if intent.open_within_months:
        acknowledged.append({"label": f"Open in ~{intent.open_within_months} mo", "value": "timeline", "source": "stated"})
    if intent.tenure == "buy":
        acknowledged.append({"label": "Buying, not leasing", "value": "tenure", "source": "stated"})

    return {
        "business_type": intent.business_type,
        "business_label": cfg["label"],
        "acknowledged": acknowledged,
        "size": {"target_sqft": target, "min_sqft": lo, "max_sqft": hi, "basis": size_basis},
        "occupancy": {"counts": counts, "group": group_key, "group_label": group["label"], "occupant_load": occupant_load, "area_based_load": area_load, "people_stated": people, "basis": load_basis},
        "code": code,
        "building": {
            "suitable_types": cfg["suitable_building_types"], "acceptable_types": cfg.get("acceptable_building_types", []),
            "ground_floor": prog["ground_floor"], "min_ceiling_ft": prog["min_ceiling_ft"], "ceiling_reason": prog["ceiling_reason"],
            "buildout_months": bm,
        },
        "needs": needs,
        "timeline": timeline,
        "tenure": intent.tenure,
        "near": intent.near,
        "avoid": intent.avoid,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------- building vs. program

def facts_from(candidate: dict, feature: dict | None, building: dict | None = None) -> dict:
    """Building facts for site_checks. `building` is services/building_facts.facts() output: CoStar's
    recorded values (stories, ceiling height, sprinklers, parking spaces) win over aerial estimates."""
    s = (primary_structure(feature) or {}) if feature else {}
    parcel = (feature or {}).get("properties", {})
    known = (building or {}).get("facts", {})

    def fact(fid: str):
        """Only values CoStar recorded: aerial estimates are already read directly from the feature below."""
        f = known.get(fid)
        return f.get("value") if isinstance(f, dict) and f.get("source") == "CoStar" else None

    return {
        "building_type": candidate.get("building_type") or s.get("building-type.class"),
        "footprint_sqft": candidate.get("area_sqft") or s.get("footprint.area"),
        "stories": fact("stories") or candidate.get("stories_est") or stories_estimate(s),
        "stories_recorded": fact("stories"),
        "roof_height_ft": s.get("roof-characteristics.height"),
        "paved_sqft": parcel.get("hardscapes.area"),
        "rentable_sqft": candidate.get("rentable_sqft"),
        "space_count": candidate.get("space_count") or 0,
        "available_sqft": candidate.get("available_sqft"),
        "best_space": candidate.get("best_space"),
        "ceiling_height_ft": fact("ceiling_height_ft"),
        "sprinklers": fact("sprinklers"),
        "parking_spaces": fact("parking_spaces"),
    }


def site_checks(program: dict, facts: dict) -> list[dict]:
    """Compare a building's known facts with the program: pass | risk | unknown, each with the reason."""
    out: list[dict] = []
    size, bld = program["size"], program["building"]
    must = {n["id"] for n in program["needs"] if n["priority"] == "must"}
    fp, stories, btype = facts.get("footprint_sqft"), facts.get("stories"), facts.get("building_type")

    best = facts.get("best_space")
    if best:
        where = ('Suite ' + str(best['suite'])) if best.get('suite') else 'a space'
        if size["min_sqft"] <= best["sqft"] <= size["max_sqft"]:
            out.append({"id": "size", "label": "Size", "status": "pass", "detail": f"CoStar lists {where} with {best['sqft']:,.0f} rentable sq ft, inside your {size['min_sqft']:,}-{size['max_sqft']:,} sq ft range"})
        else:
            out.append({"id": "size", "label": "Size", "status": "risk", "detail": f"The closest listed space ({where}, {best['sqft']:,.0f} rentable sq ft) is outside your {size['min_sqft']:,}-{size['max_sqft']:,} sq ft range; ask whether it can be " + ("divided" if best["sqft"] > size["max_sqft"] else "expanded or combined")})
    elif facts.get("space_count"):
        out.append({"id": "size", "label": "Size", "status": "risk", "detail": f"CoStar lists {facts['space_count']} space(s) ({facts.get('available_sqft') or 0:,.0f} sq ft in total), none in your {size['min_sqft']:,}-{size['max_sqft']:,} sq ft range; ask whether spaces can be combined or divided"})
    elif fp:
        if fp >= size["min_sqft"]:
            out.append({"id": "size", "label": "Size", "status": "pass", "detail": f"Building footprint {fp:,.0f} sq ft (one floor; no rentable figure) covers the {size['min_sqft']:,}-{size['max_sqft']:,} sq ft you need" + (" (you would lease part of it)" if fp > size["max_sqft"] * 2 else "")})
        elif stories and stories > 1 and fp * stories >= size["min_sqft"]:
            out.append({"id": "size", "label": "Size", "status": "risk", "detail": f"Only {fp:,.0f} sq ft per floor: your ~{size['target_sqft']:,} sq ft would span {math.ceil(size['target_sqft'] / fp)} floors"})
        else:
            out.append({"id": "size", "label": "Size", "status": "risk", "detail": f"{fp:,.0f} sq ft is below the ~{size['min_sqft']:,} sq ft minimum for your program"})
    else:
        out.append({"id": "size", "label": "Size", "status": "unknown", "detail": "Building area unknown"})

    gf = (best or {}).get("ground_floor") if best else None
    if (bld["ground_floor"] != "any" or "ground_floor" in must or "accessibility" in must) and gf is not None:
        suite = f"Suite {best['suite']}" if best.get("suite") else "The listed space"
        out.append({"id": "ground_floor", "label": "Ground floor", "status": "pass" if gf else "risk",
                    "detail": f"{suite} is on the {best['floor'].lower()}" + ("" if gf else (" (this use needs street level)" if bld["ground_floor"] == "required" else "; upper floors need an elevator for accessibility"))})
    elif bld["ground_floor"] != "any" or "ground_floor" in must or "accessibility" in must:
        recorded = facts.get("stories_recorded")  # CoStar; aerial estimates can't confirm street level
        if btype and btype in bld["acceptable_types"]:
            out.append({"id": "ground_floor", "label": "Ground floor", "status": "risk", "detail": f"{btype.replace('_', ' ').title()} building: a ground-floor commercial suite must exist and be available"})
        elif recorded == 1:
            out.append({"id": "ground_floor", "label": "Ground floor", "status": "pass", "detail": "Single-story building (CoStar record): the whole space is at street level"})
        elif stories == 1:
            out.append({"id": "ground_floor", "label": "Ground floor", "status": "unknown", "detail": "Aerial data suggests a single story (estimate, not verified): confirm the space is at street level"})
        elif stories:
            out.append({"id": "ground_floor", "label": "Ground floor", "status": "unknown", "detail": f"{'' if recorded else '~'}{stories} stories: confirm the available suite is on the ground floor" + (" (required for this use)" if bld["ground_floor"] == "required" else "")})

    rh = facts.get("roof_height_ft")
    measured = facts.get("ceiling_height_ft")
    if isinstance(measured, (int, float)) and measured > 0:
        status = "pass" if measured >= bld["min_ceiling_ft"] else "risk"
        out.append({"id": "ceiling", "label": "Ceiling height", "status": status, "detail": f"CoStar lists {measured:.0f} ft ceilings vs {bld['min_ceiling_ft']}+ ft wanted" + ("" if status == "pass" else f". {bld['ceiling_reason']}")})
    elif isinstance(rh, (int, float)) and stories:
        clear = rh / stories - 3  # ~3 ft of structure and ducts per floor
        status = "pass" if clear >= bld["min_ceiling_ft"] else "risk"
        out.append({"id": "ceiling", "label": "Ceiling height", "status": status, "detail": f"~{clear:.0f} ft clear per floor (estimated from a {rh:.0f} ft roof, {stories} floor{'s' if stories > 1 else ''}) vs {bld['min_ceiling_ft']}+ ft wanted" + ("" if status == "pass" else f". {bld['ceiling_reason']}")})

    paved = facts.get("paved_sqft")
    registry = needs_registry()
    for need in program["needs"]:
        check = need.get("check") or registry.get(need["id"], {}).get("check")
        if check == "parking":
            want = math.ceil(size["target_sqft"] / 1000 * 4)
            spaces = facts.get("parking_spaces")
            if isinstance(spaces, (int, float)) and spaces > 0:
                out.append({"id": need["id"], "label": "Parking", "status": "pass" if spaces >= want else "risk", "detail": f"CoStar lists {spaces:,.0f} parking spaces at the building (shared with other tenants) vs ~{want} a typical customer base needs (the city minimum is checked by the Compliance Agent)"})
                continue
            have = math.floor(paved / SQFT_PER_PARKING_SPACE) if paved else None
            out.append({"id": need["id"], "label": "Parking", "status": "unknown" if have is None else "pass" if have >= want else "risk", "detail": "No paving data" if have is None else f"Paved area fits ~{have} spaces vs ~{want} a typical customer base needs (the city minimum is checked by the Compliance Agent)"})
        elif check == "paved_area":
            spec = registry.get(need["id"], {})
            min_paved, what = spec.get("min_paved_sqft"), spec.get("paved_reason", "this need uses outdoor paved area")
            if not min_paved:
                continue
            out.append({"id": need["id"], "label": need["label"], "status": "unknown" if not paved else "pass" if paved >= min_paved else "risk", "detail": "No paving data" if not paved else f"{paved:,.0f} sq ft of paving on the parcel; {what}"})

    if program["timeline"]:
        t = program["timeline"]
        out.append({"id": "timeline", "label": "Timeline", "status": {"ok": "pass", "tight": "risk", "risk": "risk"}[t["status"]], "detail": t["detail"]})
    for c in program["code"]:
        if c["id"] == "sprinklers" and c["value"] == "Likely required":
            has = facts.get("sprinklers")
            if has is True:
                out.append({"id": "sprinklers", "label": "Sprinklers", "status": "pass", "detail": "Your program likely needs sprinklers; CoStar lists the building as sprinklered (confirm coverage of the suite)"})
            elif has is False:
                out.append({"id": "sprinklers", "label": "Sprinklers", "status": "risk", "detail": "Your program likely needs sprinklers, and CoStar lists no sprinkler system: a retrofit (or a smaller occupant load) is likely needed"})
            else:
                out.append({"id": "sprinklers", "label": "Sprinklers", "status": "unknown", "detail": "Your program likely needs sprinklers; aerial data cannot show whether the building has them"})
        if c["id"] == "exits" and c["value"].startswith(("2", "3", "4")):
            out.append({"id": "exits", "label": "Exits", "status": "unknown", "detail": f"Needs {c['value']}; confirm the suite has a second exit (rear door or corridor)"})
    return out


def compliance_rows(program: dict, checks: list[dict]) -> list[dict]:
    """Program code needs + building checks as compliance items (pass | risk | unknown) for the dashboard."""
    rows: dict[str, dict] = {}
    for c in program["code"]:
        if c["id"] == "occupancy_group":
            continue
        status = "pass" if (c["id"] == "exits" and c["value"].startswith("1")) or (c["id"] == "sprinklers" and c["value"] != "Likely required") else "unknown"
        rows[c["id"]] = {"id": f"program_{c['id']}", "rule": f"{c['rule']}: {c['value']}", "status": status, "detail": c["detail"], "citation": c.get("citation"), "url": None}
    for k in checks:
        if k["id"] == "size":
            continue
        base = rows.get(k["id"])
        rows[k["id"]] = {"id": f"program_{k['id']}", "rule": base["rule"] if base else k["label"], "status": k["status"], "detail": k["detail"], "citation": base.get("citation") if base else None, "url": None}
    return list(rows.values())
