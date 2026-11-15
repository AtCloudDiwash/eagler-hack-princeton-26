"""Matterport Agent: interior layout, room mix, ceiling heights, doors and windows from the 3D scan
(Matterport Model API) linked to the selected building.

Runs when the building has a linked tour AND interior data is reachable (API credentials or a recorded
scan). Before investigating it checks the scan's identity (services/scan_identity.py): a scan of a
different building is not used, a scan of a building amenity (fitness center, lobby) is used as
building-level evidence only, and an auto-linked amenity scan is replaced by a better CoStar scan of the
same property when one exists. The scan's deterministic facts (services.matterport.interior_facts) are
registered as one evidence item and shared with the engine via ctx.shared.

Like every agent it cites evidence ids; "not found in the scan" is an open question, never proof of absence.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

import db
from agents.base import AgentReport, RunContext, ToolBudget, deterministic_report, run_agent, tracked_tool
from schemas import AgentFinding, AgentMetricAssessment
from services import matterport, scan_identity

log = logging.getLogger("turnkey.agents.matterport")

SOURCE = "Matterport Model API (3D interior scan)"
ROLE_BASE = (
    "You examine the interior of the selected building from its Matterport 3D scan. Decide what the user's "
    "business needs inside (kitchen, restrooms, open floor, private rooms, clear height, accessible doors, "
    "loading doors, daylight), check each need against the scan data, and say plainly what the scan cannot show."
)

INTERIOR_QUESTIONS = {
    "restaurant": ["Is there an existing hood, grease interceptor or gas line?", "Ceiling height and clear path for exhaust ductwork", "Restroom count and accessibility"],
    "dental_clinic": ["Room sizes for 4-6 operatories", "Existing plumbing locations (sinks, slab penetrations)", "Electrical panel capacity"],
    "gym": ["Clear ceiling height and column spacing", "Floor type (slab on grade?)", "Locker/shower rooms"],
    "office": ["Open vs. private office layout", "Ceiling height, windows and daylight", "Restrooms and kitchenette"],
    "retail": ["Storefront width and glazing", "Sales floor vs. storage split", "Ceiling height"],
}

NOT_SEEN = "A scan shows what was visible on capture day. Not finding something in the scan means 'unverified', not 'absent'."
PI_NOTE = "Areas, ceiling heights and openings are Matterport Property Intelligence estimates; large or irregular rooms can return no height."
CLASSIFIER_NOTE = "Rooms without a name are typed by Matterport's residential room classifier (e.g. Bathroom, Bedroom, Hallway); a name set by the scanner wins."
ADA_CLEAR_IN = 32


def available(ctx: RunContext) -> tuple[bool, str]:
    model_id = ctx.property.get("matterport_model_id")
    if not model_id:
        return False, "No Matterport tour is linked to this property (paste one on the building panel)."
    if matterport.data_mode(model_id) == "embed_only":
        return False, "A Matterport tour is linked (viewable in the dashboard), but interior data needs MATTERPORT_API_KEY / MATTERPORT_API_SECRET or a recorded scan."
    return True, ""


def role(facts: dict) -> str:
    """ROLE plus an honest list of what THIS scan contains."""
    tiers = facts["tiers_available"]
    has = ["floors and rooms (names set by the scanner, otherwise a residential room classifier)", "any tags, labels, notes or measurements the owner added"]
    if "pi" in tiers:
        has.append("room areas and ceiling heights")
    if "boundary" in tiers:
        has.append("door and window openings with their sizes")
    if facts["objects_available"]:
        has.append("detected objects")
    lacks = "hidden utilities (plumbing, gas, electrical capacity), code compliance" + ("" if facts["objects_available"] else ", and fixtures or equipment (sinks, hoods, stoves): this scan has no object detection, so those can only be checked by watching the 3D tour")
    return f"{ROLE_BASE}\nThis scan contains: {'; '.join(has)}.\nIt does not contain: {lacks}."


def _min_ceiling(ctx: RunContext) -> float:
    return float(((ctx.program or {}).get("building") or {}).get("min_ceiling_ft") or 9.0)


def build_tools(ctx: RunContext, budget: ToolBudget, scan: dict, facts: dict | None = None, identity: dict | None = None) -> list:
    tool = tracked_tool(ctx, "matterport", budget, SOURCE)
    facts = facts or matterport.interior_facts(scan)
    identity = identity or {"verdict": "unknown", "reason": "Scan identity was not checked.", "model_id": scan["model_id"]}
    url = matterport.embed_url(scan["model_id"])
    rooms = scan["rooms"]
    tiers = facts["tiers_available"]
    area = facts["indoor_area_with_walls_sqft"] or facts["indoor_area_sqft"]

    @tool
    def get_scan_identity() -> dict:
        """Which space this scan shows: its name, address and distance from the building, and a verdict
        (verified / likely / amenity / mismatch / unknown). Call this first; an amenity scan (e.g. a fitness
        center) only supports building-level findings."""
        dist = f", {identity['distance_m']:,} m from the building" if identity.get("distance_m") is not None else ""
        return {"summary": f"Scan identity {identity['verdict']}: '{identity.get('name') or scan['model_id']}'{dist}. {identity['reason']}", "data": identity, "url": url}

    @tool
    def get_scan_overview() -> dict:
        """Floors, measured indoor area, room count and room types, owner annotations, and which data the scan includes."""
        types: dict[str, int] = {}
        for r in rooms:
            k = r.get("category") or (r["type"] or "unclassified").lower()
            types[k] = types.get(k, 0) + 1
        data = {
            "scan_name": scan["name"], "captured": scan["captured"], "floors": scan["floors"],
            "total_indoor_area_sqft": scan["total_indoor_area_sqft"], "total_indoor_area_with_walls_sqft": scan.get("total_indoor_area_with_walls_sqft"),
            "room_count": len(rooms), "room_types": types, "rooms_by_type": facts["rooms_by_type"],
            "tag_count": len(scan["tags"]), "owner_annotations": facts["owner_annotations"],
            "detected_object_count": len(scan["objects"]), "data_tiers": tiers,
            "dimensions_and_objects_available": scan["insights_available"],
        }
        a = f"{area:,.0f} sq ft measured" if area else "area not measured"
        return {
            "summary": f"Scan '{scan['name'] or scan['model_id']}': {len(scan['floors'])} floor(s), {len(rooms)} rooms, {a}",
            "data": data, "url": url, "guidance": [PI_NOTE, CLASSIFIER_NOTE, *facts["notes"]],
        }

    @tool
    def list_rooms(floor: str | None = None) -> dict:
        """Every room with its name, category, floor, area, ceiling height and door/window counts. Optionally filter by floor label."""
        hits = [r for r in rooms if not floor or (r["floor"] or "").lower() == floor.lower()]
        data = [{
            **{k: r[k] for k in ("label", "category", "type", "floor", "area_sqft", "height_ft", "width_ft", "depth_ft")},
            "name_source": r.get("label_source"), "ceiling_min_ft": r.get("ceiling_min_ft"), "ceiling_max_ft": r.get("ceiling_max_ft"),
            "doors": sum(1 for o in r.get("openings") or [] if o["type"] != "window"), "windows": sum(1 for o in r.get("openings") or [] if o["type"] == "window"),
        } for r in hits[:40]]
        return {"summary": f"{len(hits)} rooms" + (f" on {floor}" if floor else "") + ": " + ", ".join(r["label"] for r in hits[:12]), "data": data, "url": url, "guidance": [CLASSIFIER_NOTE, PI_NOTE]}

    @tool
    def count_rooms_of_type(room_type: Literal["kitchen", "restroom", "office", "storage", "open_area"]) -> dict:
        """Rooms of one commercial type, matched on whole words of the room's name (or the classifier label
        when unnamed): restroom = bathroom/toilet/WC; kitchen = kitchenette/pantry/breakroom; office =
        office/conference/meeting; storage = closet/utility/mechanical; open_area = lobby/showroom/retail/
        dining/open office/warehouse/gym/studio (hallways are not open area)."""
        hits = [r for r in rooms if r.get("category") == room_type]
        data = {"room_type": room_type, "count": len(hits), "rooms": [{k: r.get(k) for k in ("label", "type", "floor", "area_sqft", "height_ft")} for r in hits], "total_area_sqft": round(sum(r["area_sqft"] or 0 for r in hits)) or None}
        return {"summary": f"{len(hits)} {room_type.replace('_', ' ')} room(s) in the scan" + (f": {', '.join(r['label'] for r in hits[:6])}" if hits else ""), "data": data, "url": url, "guidance": [NOT_SEEN, CLASSIFIER_NOTE]}

    objects_hint = " and detected objects" if facts["objects_available"] else ""

    def search_scan(keyword: str) -> dict:
        found = matterport.search(scan, keyword)
        n = sum(len(v) for v in found.values())
        parts = ", ".join(f"{len(v)} {k}" for k, v in found.items() if v) or "nothing"
        return {"summary": f"'{keyword}': {n} match(es) ({parts})", "data": found, "url": url, "guidance": [NOT_SEEN]}

    search_scan.__doc__ = (
        f"Whole-word search of room names, owner tags, labels, notes and measurements{objects_hint} for one keyword, "
        "e.g. 'kitchen', 'restroom', 'storage', 'stairs', 'elevator', 'loading'. "
        + ("" if facts["objects_available"] else "This scan has no object detection: equipment such as a hood or sink is found only if the owner named or tagged it.")
    )
    tools = [get_scan_identity, get_scan_overview, list_rooms, count_rooms_of_type, tool(search_scan)]

    if "pi" in tiers:
        default_ft = _min_ceiling(ctx)

        def check_ceiling_heights(min_clear_ft: float | None = None) -> dict:
            threshold = float(min_clear_ft or default_ft)
            c = facts["ceiling"]
            measured = [r for r in rooms if r.get("ceiling_min_ft") or r.get("height_ft")]
            share = f"{c['measured_area_share']:.0%} of floor area" if c["measured_area_share"] is not None else "unknown share of floor area"
            unmeasured = "; largest unmeasured: " + ", ".join(f"{u['label']}" + (f" {u['area_sqft']:,.0f} sq ft" if u["area_sqft"] else "") for u in c["unmeasured_rooms"][:3]) if c["unmeasured_rooms"] else ""
            if not measured:
                return {"summary": "No ceiling heights measured in this scan" + unmeasured, "data": {"threshold_ft": threshold, **c}, "url": url, "guidance": [PI_NOTE]}
            low = [{"label": r["label"], "height_ft": r.get("ceiling_min_ft") or r["height_ft"]} for r in measured if (r.get("ceiling_min_ft") or r["height_ft"]) < threshold]
            data = {**c, "rooms_measured": len(measured), "rooms_unmeasured": len(rooms) - len(measured), "threshold_ft": threshold, "rooms_below_threshold": low}
            return {
                "summary": f"Ceilings {c['min_ft']}-{c['max_ft']} ft (median {c['median_ft']}) measured in {share}; {len(low)} of {len(measured)} measured rooms below {threshold:g} ft{unmeasured}",
                "data": data, "url": url,
                "guidance": [PI_NOTE, "Height is to the finished ceiling; space above a drop ceiling may add clearance.",
                             "Unmeasured rooms (often the largest open area) are unknown, not low or high: check them in the 3D tour."],
            }

        check_ceiling_heights.__doc__ = (
            f"Measured ceiling heights: min / max / median, the share of floor area that was measured, the largest "
            f"unmeasured rooms, and rooms below `min_clear_ft` (default {default_ft:g} ft from the user's program; "
            "e.g. ~10 ft for kitchen exhaust ducts, 12+ ft for a gym)."
        )
        tools.append(tool(check_ceiling_heights))

    if "boundary" in tiers:
        @tool
        def check_doorways() -> dict:
            """Door openings measured in the scan: the narrowest door vs. the ADA 32 in clear width, doors that may be
            tight once the door leaf is deducted, low headroom, and wide (>= 96 in) openings such as roll-up or dock doors."""
            doors = facts["doorways"]
            if not doors:
                return {"summary": "No door openings recorded in the scan's room boundaries", "data": None, "url": url, "guidance": [NOT_SEEN]}
            below = [d for d in doors if d["width_in"] < ADA_CLEAR_IN]
            tight = [d for d in doors if ADA_CLEAR_IN <= d["width_in"] < ADA_CLEAR_IN + 2 and d["kind"] != "open passage"]
            low = [d for d in doors if d["height_in"] and d["height_in"] < 80]
            wide = [d for d in doors if d["width_in"] >= matterport.WIDE_DOOR_IN]
            data = {"door_count": len(doors), "narrowest_door_in": facts["narrowest_door_in"], "below_32_in": below, "possibly_tight": tight,
                    "headroom_below_80_in": low, "wide_doors": wide, "all_doors": doors[:30]}
            return {
                "summary": f"{len(doors)} door openings; narrowest {facts['narrowest_door_in']} in; {len(below)} under {ADA_CLEAR_IN} in, {len(tight)} possibly tight; {len(wide)} wide (>= 96 in) opening(s)",
                "data": data, "url": url,
                "guidance": ["Widths are the measured opening; ADA clear width (32 in min) is measured with the door open 90 degrees, about 2 in less than the opening for a hinged door.",
                             "A door shared by two rooms is listed once ('Room A / Room B').", "Wide openings of kind 'open passage' are cased openings between areas; wide doorways may be overhead/roll-up or dock doors. Confirm in the tour."],
            }

        @tool
        def check_windows() -> dict:
            """Window openings measured in the scan: count, total glazing width and which rooms have windows (daylight, storefront)."""
            w = facts["windows"]
            return {
                "summary": f"{w['count']} window(s), {w['total_width_ft']} ft of total width" + (f", in: {', '.join(w['rooms'][:8])}" if w["rooms"] else ""),
                "data": w, "url": url,
                "guidance": ["The scan does not say which wall faces the street; storefront glazing must be confirmed in the tour or street imagery.", NOT_SEEN],
            }

        tools += [check_doorways, check_windows]

    if area:
        @tool
        def compare_area_to_need() -> dict:
            """Measured indoor area of the scan (including interior walls when available) vs. the user's space need."""
            ratio = area / ctx.target_sqft
            verdict = "fits" if 0.85 <= ratio <= 1.6 else "larger than needed" if ratio > 1.6 else "smaller than needed"
            basis = "indoor area incl. walls" if facts["indoor_area_with_walls_sqft"] else "room area (excl. walls)"
            return {
                "summary": f"Measured interior {area:,.0f} sq ft ({basis}) vs need ~{ctx.target_sqft:,} sq ft ({ratio:.2f}x): {verdict}",
                "data": {"measured_indoor_sqft": area, "measured_basis": basis, "indoor_area_sqft": facts["indoor_area_sqft"], "need_sqft": ctx.target_sqft, "need_basis": ctx.target_basis, "ratio": round(ratio, 2)},
                "url": url,
                "guidance": ["Leasable (rentable) area adds a share of common areas, usually 5-15% more than measured interior area."
                             if facts["indoor_area_with_walls_sqft"] else "Measured room area excludes walls and shafts; leasable area is usually 10-15% larger."],
            }

        tools.append(compare_area_to_need)
    return tools


def task_prompt(ctx: RunContext, focus: str | None = None, identity: dict | None = None, facts_eid: str | None = None) -> str:
    p = ctx.property
    base = (
        f"Investigate the interior of the building at {p.get('address') or f'{p['lat']:.5f}, {p['lon']:.5f}'} from its Matterport scan "
        f"for this purpose: \"{ctx.query}\".\n"
        "Decide what this business needs inside, check each need against the scan, probe anything surprising, "
        "and list what the scan cannot verify (hidden utilities, capacities, code compliance)."
    )
    if facts_eid:
        base += f"\nThe scan's measured facts (areas, room counts, ceilings, doors, windows, identity) are already recorded as evidence {facts_eid}; you may cite it."
    if identity and identity.get("switched"):
        base += f"\nNOTE: the building's linked scan {identity['linked_model_id']} was set aside ({identity['linked_verdict']}); you are analyzing scan '{identity.get('name')}' ({identity['model_id']}) instead."
    if identity and identity.get("verdict") == "amenity":
        base += ("\nIMPORTANT: this scan most likely shows a shared building AMENITY, not the space for lease "
                 f"({identity['reason']}). Treat findings as building-level only (construction, ceilings, finishes, accessibility) "
                 "and mark the suite's own layout, room mix and size as unknown.")
    elif identity and identity.get("verdict") in ("likely", "unknown"):
        base += f"\nScan identity: {identity['verdict']} ({identity['reason']})"
    if focus:
        base += f"\n\nFOLLOW-UP FROM THE LEAD ENGINE: {focus}\nFocus only on resolving this; use at most 3 tool calls."
    return base


def _skipped(ctx: RunContext, reason: str) -> AgentReport:
    questions = list(INTERIOR_QUESTIONS.get(ctx.intent["business_type"], ["Interior layout and measurements"]))
    questions += [n["label"] for n in (ctx.program or {}).get("needs", []) if n.get("owner") == "matterport" and n.get("label") not in questions]
    metrics = ctx.metrics_for("matterport")
    ctx.emit("matterport", "skipped", f"Skipped: {reason}", None)
    return deterministic_report(
        ctx,
        "matterport",
        f"Interior data unavailable: {reason} Interior layout and infrastructure are unknown and excluded from the score.",
        [AgentMetricAssessment(metric_id=m["id"], status="unknown", rationale=f"No interior scan data: {reason}") for m in metrics],
        [AgentFinding(title="Interior not inspected", detail=reason, impact="neutral", severity="medium", kind="fact", why_it_matters="Interior conditions often decide conversion cost; they remain unverified.", metric_ids=[m["id"] for m in metrics])],
        questions,
    )


def facts_line(model_id: str, identity: dict, facts: dict) -> str:
    """One-line summary of the scan facts evidence item."""
    parts = [f"Scan {model_id} ({identity['verdict']})"]
    area = facts["indoor_area_with_walls_sqft"] or facts["indoor_area_sqft"]
    if area:
        parts.append(f"{area:,.0f} sq ft" + (" incl. walls" if facts["indoor_area_with_walls_sqft"] else ""))
    rt = ", ".join(f"{n} {t.replace('_', ' ')}" for t, n in facts["rooms_by_type"].items() if n)
    if rt:
        parts.append(rt)
    c = facts["ceiling"]
    if c["min_ft"] is not None:
        parts.append(f"ceilings {c['min_ft']}-{c['max_ft']} ft" + (f" in {c['measured_area_share']:.0%} of area" if c["measured_area_share"] is not None else ""))
    if facts["doorways"]:
        parts.append(f"{len(facts['doorways'])} doors (narrowest {facts['narrowest_door_in']} in, {facts['wide_doors']} wide)")
    if facts["windows"]["count"] is not None:
        parts.append(f"{facts['windows']['count']} windows")
    return "; ".join(parts)


async def _suite_tour_identity(ctx: RunContext, linked: str, auto_linked: bool) -> dict | None:
    """When the building's live tour list has a strong tour of the listed suite, analyze that tour as 'verified'
    (older than STALE_YEARS: 'likely'). None when there is no such tour, or the user linked a different one."""
    from services import costar, suite_tours

    try:
        rec = costar.match(ctx.property["lat"], ctx.property["lon"], ctx.property.get("footprint"))
        tours = await asyncio.wait_for(suite_tours.building_tours(ctx.property, rec), timeout=15)
    except Exception as err:  # noqa: BLE001 - fall back to the per-scan identity check
        log.info("suite tours unavailable: %s", err)
        return None
    ctx.shared["building_tours"] = tours
    m = suite_tours.match(tours, ctx.property.get("best_space"))
    if not m or m["confidence"] != "strong" or not (auto_linked or linked == m["id"]):
        return None
    t = next(x for x in tours if x["id"] == m["id"])
    stale = bool(t.get("age_years") and t["age_years"] > scan_identity.STALE_YEARS)
    reason = f"Tour '{t['name']}' shows the listed suite: " + "; ".join(m["signals"]) + (f". Caveats: {'; '.join(m['caveats'])}" if m["caveats"] else "") + "."
    return {"verdict": "likely" if stale else "verified", "reason": reason, "model_id": m["id"], "name": t["name"], "address": t.get("line2"),
            "distance_m": t.get("distance_m"), "alternatives_checked": len(tours), "captured": t.get("captured"), "age_years": t.get("age_years"),
            "linked_model_id": linked, "linked_verdict": "suite tour" if linked == m["id"] else "other tour", "switched": m["id"] != linked, "alternative": None}


async def run(ctx: RunContext, budget_limit: int = 6, focus: str | None = None, metric_ids: list[str] | None = None) -> AgentReport:
    ok, reason = available(ctx)
    if not ok:
        return _skipped(ctx, reason)
    linked = ctx.property["matterport_model_id"]
    auto_linked = bool(ctx.property.get("matterport_auto_model_id")) and ctx.property.get("matterport_auto_model_id") == linked
    identity = await _suite_tour_identity(ctx, linked, auto_linked) or await scan_identity.choose_scan(ctx.property, allow_switch=auto_linked)
    ctx.shared["scan_identity"] = identity
    if identity["verdict"] == "residential":
        return _skipped(ctx, f"The linked Matterport scan is an apartment-unit tour, not the commercial space: {identity['reason']} (Link a tour of the space on the building panel.)")
    if identity["verdict"] == "mismatch":
        alt = identity.get("alternative")
        hint = f" A matching scan may be '{alt.get('name')}' ({alt['model_id']}); link it on the building panel." if alt else ""
        return _skipped(ctx, f"The linked Matterport scan doesn't show this building: {identity['reason']}{hint} (The tour still plays in the dashboard.)")

    model_id = identity["model_id"] if identity.get("switched") else linked
    loaded = ctx.shared.get("matterport_scan")
    if loaded and loaded[0] == model_id:  # a follow-up: reuse the scan and its evidence
        _, scan, facts, eid = loaded
    else:
        try:
            scan = matterport.summarize(await matterport.fetch_model(model_id))
        except Exception as err:  # noqa: BLE001 - API/network failure must not sink the analysis
            return _skipped(ctx, f"Could not load Matterport model {model_id}: {err}")
        if not scan["rooms"] and not scan["floors"]:
            return _skipped(ctx, f"Matterport model {model_id} returned no floors or rooms.")
        if identity.get("switched"):
            # The stored building link is left as is (the user sees the same tour); the report says which scan was analyzed.
            ctx.emit("matterport", "plan", f"Using scan '{identity.get('name')}' ({model_id}) instead of the auto-linked {identity['linked_verdict']} scan {linked}", {"identity": identity})
        facts = matterport.interior_facts(scan)
        eid = ctx.evidence.add("matterport", "scan_facts", SOURCE, facts_line(model_id, identity, facts), {"identity": identity, **facts}, matterport.embed_url(model_id))
        ctx.shared["matterport_scan"] = (model_id, scan, facts, eid)
    ctx.shared["interior_facts"] = facts
    ctx.shared["interior_facts_eid"] = eid

    budget = ToolBudget(budget_limit, ctx.shared.setdefault("seen:matterport", {}))
    report = await run_agent(ctx, "matterport", role(facts), task_prompt(ctx, focus, identity, eid), build_tools(ctx, budget, scan, facts, identity), budget, metric_ids=metric_ids)
    prefix = ""
    if identity.get("switched"):
        prefix = f"Analyzed scan '{identity.get('name')}' ({model_id}) instead of the linked {identity['linked_verdict']} scan {linked}. "
    elif identity["verdict"] == "amenity":
        prefix = "The linked scan appears to show a building amenity, so these findings are building-level only. "
    return report.model_copy(update={"summary": prefix + report.summary}) if prefix else report
