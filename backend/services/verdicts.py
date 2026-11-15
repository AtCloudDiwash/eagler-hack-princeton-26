"""Metric verdicts: the statuses that data and verified rules can settle, and how agent judgments merge with them.

A metric in config/metrics.yaml may name a `resolver`. Resolvers compute the metric's status from data
the engine trusts (verified jurisdiction rules, the cost engine, the CoStar building record, Vexcel
attributes, the interior scan) using the user's program — never from numbers an agent chose. Each
verdict says which agent statuses it accepts:

- an authoritative verdict accepts its own status and anything MORE cautious (an agent may know about a
  deed restriction the rule set doesn't), never anything less cautious;
- a cap (`kind="cap"`) only rules out optimism: the agent decides, but cannot rate above the cap.

`settle(ctx)` runs every resolver once per analysis (cached in ctx.shared) and registers the evidence the
verdicts cite; `merge()` is a pure function of (agent assessments, verdicts). Running the merge twice — e.g.
after follow-ups — gives the same result.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from config import metrics_registry
from schemas import AgentMetricAssessment
from services import costs as cost_engine
from services import program as space_program
from services import rules, sizing
from services.vexcel import primary_structure, stories_estimate

RANK = {"blocker": 0, "weak": 1, "adequate": 2, "strong": 3}
RULE_STATUS = {"pass": "strong", "risk": "adequate", "fail": "blocker", "unknown": "unknown"}


@dataclass(frozen=True)
class Verdict:
    metric_id: str
    status: str  # strong | adequate | weak | blocker | unknown
    rationale: str
    evidence_ids: tuple[str, ...] = ()
    source: str = "verified data"
    kind: str = "authoritative"  # authoritative | cap
    also_accept: frozenset[str] = field(default_factory=frozenset)  # extra agent statuses accepted as-is

    def accepts(self, agent_status: str) -> bool:
        if agent_status in self.also_accept or agent_status == self.status:
            return True
        if self.status == "unknown" or agent_status in {"unknown", "blocker"}:
            return False
        return RANK[agent_status] <= RANK[self.status]  # same or more cautious


# ---------------------------------------------------------------- helpers

def _fact(ctx: Any, fact_id: str, costar_only: bool = True) -> Any:
    """A building fact's value. By default only values CoStar recorded (aerial estimates are read from the
    Vexcel feature directly, so they are never double counted or mislabelled as recorded)."""
    f = (ctx.building.get("facts") or {}).get(fact_id) if isinstance(getattr(ctx, "building", None), dict) else None
    if not isinstance(f, dict) or (costar_only and f.get("source") != "CoStar"):
        return None
    return f.get("value")


def _structure(ctx: Any) -> dict:
    return (primary_structure(ctx.feature) or {}) if ctx.feature else {}


def _evidence(ctx: Any, tool: str, summary: str, data: Any, source: str, url: str | None = None) -> str:
    """Reuse an identical result an agent already produced (same tool, same data); otherwise record it as engine evidence."""
    return ctx.evidence.find(tool, data) or ctx.evidence.add("engine", tool, source, summary, data, url)


def _program_size(ctx: Any) -> tuple[int, int, int]:
    size = (ctx.program or {}).get("size") or {}
    target = size.get("target_sqft") or ctx.target_sqft
    return target, size.get("min_sqft") or round(target * 0.85), size.get("max_sqft") or round(target * 1.3)


def interior_scan(ctx: Any) -> dict | None:
    """Interior facts from the Matterport scan, only when the scan is believed to show this space."""
    facts = ctx.shared.get("interior_facts")
    identity = ctx.shared.get("scan_identity") or {}
    verdict = identity.get("verdict")
    # "likely" = in this building but not a specific listed suite: only usable when no suite is listed, otherwise
    # it may be another tenant's floor (e.g. Suite 1080 when Suite 170 is the space for lease).
    if not facts or not (verdict in {None, "verified"} or (verdict == "likely" and not ctx.property.get("best_space"))):
        return None
    return facts


# ---------------------------------------------------------------- resolvers

def _permitted_use(ctx: Any) -> Verdict | None:
    item = rules.permitted_use(ctx.jurisdiction, ctx.intent["business_type"])
    eid = _evidence(ctx, "check_permitted_use", f"Permitted use: {item['status'].upper()} — {item['detail'][:160]}", item, item.get("citation") or "Verified rule set", item.get("url"))
    zoning = _fact(ctx, "zoning_code")
    note = f" CoStar records zoning '{zoning}'; confirm the use is allowed in that district." if zoning and ctx.jurisdiction.get("zoning_mode") != "none" else ""
    return Verdict("permitted_use", RULE_STATUS[item["status"]], f"Verified rule ({ctx.jurisdiction['name']}): {item['detail']}{note}", (eid,), "verified rules")


def _parking_requirement(ctx: Any) -> Verdict | None:
    target, _, _ = _program_size(ctx)
    parcel = (ctx.feature or {}).get("properties", {})
    item = rules.parking_requirement(ctx.jurisdiction, ctx.intent["business_type"], target, ctx.property["lat"], ctx.property["lon"], parcel.get("hardscapes.area"), _fact(ctx, "parking_spaces"))
    eid = _evidence(ctx, "compute_parking_requirement", f"Parking: {item['status'].upper()} — {item['detail'][:180]}", item, item.get("citation") or "Verified rule set", item.get("url"))
    status = {"pass": "strong", "risk": "weak", "unknown": "unknown"}.get(item["status"], "unknown")
    # A shortfall can often be solved with shared parking or a variance, so "adequate" is an acceptable agent reading.
    return Verdict("parking_requirement", status, f"Parking rule at your ~{target:,} sq ft: {item['detail']}", (eid,), "verified rules", also_accept=frozenset({"adequate"}) if status == "weak" else frozenset())


def _size_fit(ctx: Any) -> Verdict | None:
    target, lo, hi = _program_size(ctx)
    p = ctx.property
    s = _structure(ctx)
    interior = interior_scan(ctx) or {}
    graded = sizing.fit(
        {"target_sqft": target, "min_sqft": lo, "max_sqft": hi}, best_space=p.get("best_space"), closest_space_sqft=p.get("closest_space_sqft"),
        space_count=p.get("space_count") or 0, available_sqft=p.get("available_sqft"),
        interior_sqft=interior.get("indoor_area_with_walls_sqft") or interior.get("indoor_area_sqft"),
        footprint_sqft=p.get("area_sqft") or s.get("footprint.area"), stories=_fact(ctx, "stories") or p.get("stories_est") or stories_estimate(s),
        ground_floor_required=((ctx.program or {}).get("building") or {}).get("ground_floor") == "required",
    )
    if not graded:
        return None
    eid = _evidence(ctx, "size_check", graded.reason, {**graded.data, "score": round(graded.score, 2), "need_sqft": target}, "Program size vs. building/listing data")
    return Verdict("size_fit", graded.status, graded.reason, (eid,), "building data")


def _occupancy_requirements(ctx: Any) -> Verdict | None:
    if not ctx.program:
        return None
    checks = space_program.site_checks(ctx.program, space_program.facts_from(ctx.property, ctx.feature, ctx.building))
    # Code/program triggers only (ceiling height is a building-quality question, judged elsewhere). A conflict needs
    # recorded data: sprinklers (CoStar), the timeline, or a listed suite that is not at street level. Inferred risks
    # (e.g. "a ground-floor suite must exist") are things to confirm, not conflicts.
    relevant = [c for c in checks if c["id"] in {"ground_floor", "sprinklers", "timeline", "exits"}]
    suite_upstairs = (ctx.property.get("best_space") or {}).get("ground_floor") is False
    conflicts = [c for c in relevant if c["status"] == "risk" and (c["id"] != "ground_floor" or suite_upstairs)]
    unknown = [c for c in relevant if c["status"] == "unknown" or (c["status"] == "risk" and c not in conflicts)]
    if conflicts:
        status, reason = "weak", "Program conflicts with this building: " + "; ".join(f"{c['label']}: {c['detail']}" for c in conflicts)
    elif unknown:
        status, reason = "adequate", "No conflict found, but still to confirm: " + "; ".join(f"{c['label']}: {c['detail']}" for c in unknown)
    else:
        status, reason = "strong", "Building data satisfies what your program triggers: " + "; ".join(f"{c['label']}: {c['detail']}" for c in relevant) if relevant else "No code trigger in your program conflicts with this building."
    eid = _evidence(ctx, "check_space_program", f"Program vs building: {len(conflicts)} conflict(s), {len(unknown)} to confirm", {"site_checks": checks}, "IBC/IPC 2021 model code analysis of the user's program (services/program.py)")
    return Verdict("occupancy_requirements", status, reason, (eid,), "code analysis")


NOTABLE_DEFECTS = {"structural-damage": "structural damage", "tarp": "a tarp", "missing-material": "missing roof material", "patch": "patching"}
MINOR_DEFECTS = {"discoloration": "discoloration/ponding stains", "rust": "rust", "debris": "debris"}


def _building_condition(ctx: Any) -> Verdict | None:
    s = _structure(ctx)
    cond = s.get("roof-characteristics.condition")
    if not isinstance(cond, (int, float)):
        return None
    notable = [label for k, label in NOTABLE_DEFECTS.items() if s.get(f"roof-defects.{k}.detected") is True]
    minor = [label for k, label in MINOR_DEFECTS.items() if s.get(f"roof-defects.{k}.detected") is True]
    if "structural damage" in notable or cond <= 2 or notable:
        status = "weak"
    elif cond >= 4:
        status = "strong"
    else:
        status = "adequate"
    bits = [f"Roof condition {cond:.0f}/5"]
    if notable:
        bits.append("notable defects: " + ", ".join(notable))
    if minor:
        bits.append("minor: " + ", ".join(minor))
    year, renovated = _fact(ctx, "year_built"), _fact(ctx, "last_renovation_year")
    if year:
        bits.append(f"built {year}" + (f", renovated {renovated}" if renovated else ""))
    data = {"roof_condition": cond, "notable_defects": notable, "minor_defects": minor, "year_built": year, "last_renovation_year": renovated}
    eid = _evidence(ctx, "roof_condition_check", "; ".join(bits), data, "Vexcel /property/extract (+ CoStar building record)")
    return Verdict("building_condition", status, "; ".join(bits) + ".", (eid,), "aerial data")


def _hvac_ventilation(ctx: Any) -> Verdict | None:
    s = _structure(ctx)
    units = s.get("roof-objects.ac-unit.count")
    if not isinstance(units, (int, float)):
        return None
    flat = s.get("roof-characteristics.shape.value") == "flat"
    stories = _fact(ctx, "stories") or stories_estimate(s) or 1
    renovated = [x for x in (_fact(ctx, "renovated_systems") or []) if "hvac" in str(x).lower()]
    if units >= 2 and flat:
        status, reason = "strong", f"{units:.0f} rooftop units detected on a flat roof (direct roof access for curbs and exhaust)"
    elif units >= 1 or (flat and stories == 1):
        status, reason = "adequate", f"{units:.0f} rooftop unit(s) detected; {'flat' if flat else 'pitched'} roof, ~{stories} stor{'y' if stories == 1 else 'ies'}"
    else:
        status, reason = "weak", f"No rooftop units detected ('not detected' is not proof of absence) and exhaust routing is uncertain ({'flat' if flat else 'pitched'} roof, ~{stories} stories)"
    if renovated:
        reason += "; CoStar records an HVAC renovation"
    eid = _evidence(ctx, "hvac_check", reason, {"ac_units": units, "flat_roof": flat, "stories": stories, "hvac_renovated": bool(renovated)}, "Vexcel /property/extract (+ CoStar building record)")
    return Verdict("hvac_ventilation", status, reason + ".", (eid,), "aerial data")


def _cost_estimate(ctx: Any) -> tuple[str, dict] | None:
    """The estimate the cost verdicts use: the latest one, recomputed at the program size when an agent sized it outside the program."""
    ests = [(e.id, e.data) for e in ctx.evidence.all() if e.tool == "estimate_costs" and isinstance(e.data, dict)]
    if not ests:
        return None
    eid, data = ests[-1]
    target, lo, hi = _program_size(ctx)
    listed = (ctx.property.get("best_space") or {}).get("sqft")
    used = data.get("sqft_used") or target
    if lo <= used <= hi or (listed and abs(used - listed) <= 1) or "_adders" not in data:
        return eid, data
    fixed = cost_engine.estimate(ctx.intent["business_type"], target, ctx.jurisdiction_key, data["_adders"], data.get("_second_generation", False), data.get("_rent_override"))
    fixed.update({k: v for k, v in data.items() if k.startswith("_") and k != "_benchmark"})
    fixed["sqft_basis"] = f"{target:,} sq ft (your program; the agent's {used:,} sq ft was outside your {lo:,}-{hi:,} sq ft range)"
    new_id = _evidence(ctx, "estimate_costs", f"Recomputed at your program size: upfront ${fixed['upfront']['low']:,}–{fixed['upfront']['high']:,}", fixed, "Deterministic cost engine")
    return new_id, fixed


def _occupancy_cost(ctx: Any) -> Verdict | None:
    est = _cost_estimate(ctx)
    if not est:
        return None
    eid, data = est
    if ctx.intent.get("budget"):
        check = cost_engine.budget_check(data, ctx.intent["budget"], ctx.intent["business_type"])
        return Verdict("occupancy_cost", cost_engine.budget_status(check), check["note"], (eid,), "cost engine")
    status = cost_engine.cost_status(data)
    b = data["_benchmark"]
    return Verdict("occupancy_cost", status, f"Upfront ~${b['upfront_per_sqft_mid']}/sq ft vs a typical ${b['typical_good']}/sq ft for this use (cost engine).", (eid,), "cost engine")


def _conversion_risk(ctx: Any) -> Verdict | None:
    est = _cost_estimate(ctx)
    if not est:
        return None
    eid, data = est
    return Verdict("conversion_risk", cost_engine.conversion_risk_status(data), "Share of the fit-out budget resting on unverified items and contingency (cost engine).", (eid,), "cost engine")


def _competition(ctx: Any) -> Verdict | None:
    places_ok = any(src["name"].startswith("OpenStreetMap") and src["status"] == "used" for src in (ctx.neighborhood or {}).get("sources", []))
    if places_ok:
        return None
    return Verdict("competition", "unknown", "Nearby-place data was unavailable, so competition cannot be judged.", (), "data availability")


def _interior_layout(ctx: Any) -> Verdict | None:
    facts = interior_scan(ctx)
    if not facts:
        return None
    eid = ctx.shared.get("interior_facts_eid")
    min_ceiling = ((ctx.program or {}).get("building") or {}).get("min_ceiling_ft")
    ceiling = facts.get("ceiling") or {}
    reasons, cap = [], None
    if min_ceiling and ceiling.get("median_ft") and (ceiling.get("measured_area_share") or 0) >= 0.5 and ceiling["median_ft"] < min_ceiling:
        cap = "weak"
        reasons.append(f"measured ceilings ~{ceiling['median_ft']} ft (median) are below the {min_ceiling}+ ft this use needs")
    required = next((c.get("required_count") for c in (ctx.program or {}).get("code", []) if c["id"] == "restrooms"), None)
    have = (facts.get("rooms_by_type") or {}).get("restroom")
    if required and have is not None and have < required:
        cap = cap or "adequate"
        reasons.append(f"the scan shows {have} restroom(s) vs {required} toilet(s) your occupant load needs (adding one is a normal tenant improvement)")
    if not cap:
        return None
    return Verdict("interior_layout", cap, "Interior scan: " + "; ".join(reasons) + ".", (eid,) if eid else (), "interior scan", kind="cap")


BACK_OF_HOUSE = re.compile(r"closet|storage|utility|mechanical|electrical|janitor|jan\.|pantry|server|it room|shaft|attic")


def _accessibility_ada(ctx: Any) -> Verdict:
    """Accessibility from verified data only: the CoStar record (suite floor, stories, elevators, year built) and door
    widths measured in a scan verified to show the listed space. Aerial estimates and LLM judgment never decide it:
    with no verified data the status is 'unknown', and an agent cannot rate it higher than the data shows."""
    best = ctx.property.get("best_space") or {}
    stories, elevators, year = _fact(ctx, "stories"), _fact(ctx, "elevators"), _fact(ctx, "year_built")
    ground = best.get("ground_floor")
    verified: list[str] = []
    barriers: list[str] = []
    if ground is False:
        floor = str(best.get("floor") or "an upper floor").lower()
        if elevators == 0:
            barriers.append(f"the listed suite is on the {floor} and CoStar records no elevator")
        elif isinstance(elevators, (int, float)) and elevators > 0:
            verified.append(f"the listed suite is on the {floor}, with {elevators:.0f} elevator(s) recorded (CoStar)")
    elif ground is True:
        verified.append(f"the listed suite is at street level ({best.get('floor')}, CoStar listing)")
    elif stories == 1:
        verified.append("single-story building (CoStar)")
    doors_ok = False
    identity = ctx.shared.get("scan_identity") or {}
    scan = ctx.shared.get("interior_facts") if identity.get("verdict") == "verified" else None
    if scan and scan.get("doorways"):
        public = [d for d in scan["doorways"] if d.get("width_in") and not all(BACK_OF_HOUSE.search(part.strip().lower()) for part in str(d.get("room") or "").split("/"))]
        narrow = [d for d in public if d["width_in"] < 32]
        if narrow:
            barriers.append("measured door(s) under 32 in clear: " + ", ".join(f"{d['room']} {d['width_in']:.0f} in" for d in narrow[:3]) + " (Matterport scan of this suite)")
        elif public:
            doors_ok = True
            verified.append(f"all {len(public)} measured customer-area doors are 32 in or wider (Matterport scan of this suite)")
    pre_ada = isinstance(year, int) and year < 1991
    if pre_ada and (verified or barriers):
        verified.append(f"built {year}, before the 1991 ADA standards: expect upgrades unless renovated")
    data = {"listed_suite_floor": best.get("floor"), "listed_suite_ground_floor": ground, "stories": stories, "elevators": elevators,
            "year_built": year, "scan_verdict": identity.get("verdict"), "verified": verified, "barriers": barriers}
    if barriers:
        status = "weak"
    elif not verified:
        status = "unknown"
    elif doors_ok and not pre_ada:
        status = "strong"
    else:
        status = "adequate"
    if status == "unknown":
        reason = "No verified accessibility data for this space: the step-free entrance, accessible route, door widths and restroom need a site visit or a scan of the listed suite."
    else:
        reason = "; ".join([*barriers, *verified]).capitalize() + (". Not verified: entrance step, route to the suite and restroom layout." if status != "strong" else ". Entrance step and restroom layout still need a site check.")
    eid = _evidence(ctx, "accessibility_check", reason, data, "CoStar building record + verified Matterport scan (aerial estimates excluded)")
    return Verdict("accessibility_ada", status, reason, (eid,), "verified accessibility data")


RESOLVERS: dict[str, Callable[[Any], Verdict | None]] = {
    "permitted_use_rule": _permitted_use,
    "parking_rule": _parking_requirement,
    "size_program": _size_fit,
    "occupancy_code": _occupancy_requirements,
    "roof_condition": _building_condition,
    "rooftop_hvac": _hvac_ventilation,
    "cost_engine_budget": _occupancy_cost,
    "cost_engine_uncertainty": _conversion_risk,
    "places_required": _competition,
    "interior_scan_cap": _interior_layout,
    "accessibility_verified": _accessibility_ada,
}


def settle(ctx: Any) -> dict[str, Verdict]:
    """Run every resolver named in metrics.yaml for this business's metrics, once per analysis."""
    if "verdicts" in ctx.shared:
        return ctx.shared["verdicts"]
    reg = metrics_registry()
    out: dict[str, Verdict] = {}
    for mid in ctx.business["metrics"]:
        name = (reg.get(mid) or {}).get("resolver")
        fn = RESOLVERS.get(name or "")
        if not fn:
            continue
        try:
            v = fn(ctx)
        except Exception as err:  # noqa: BLE001 - a resolver bug must not sink the analysis; the agent's view stands
            ctx.emit("engine", "error", f"Resolver '{name}' for {mid} failed: {err}", None)
            v = None
        if v:
            out[mid] = v
    ctx.shared["verdicts"] = out
    return out


# ---------------------------------------------------------------- merge

@dataclass
class Merged:
    owner: str
    assessment: AgentMetricAssessment
    overridden: bool = False


def apply(mid: str, owner: str, agent: AgentMetricAssessment | None, verdict: Verdict | None, agent_label: str) -> tuple[Merged | None, str | None]:
    """Combine one metric's agent assessment with its verdict. Returns (merged, conflict description or None). Pure."""
    if verdict is None:
        return (Merged(owner, agent) if agent else None), None
    if agent and verdict.accepts(agent.status):
        evidence = sorted({*agent.evidence_ids, *verdict.evidence_ids})
        return Merged(owner, agent.model_copy(update={"evidence_ids": evidence})), None
    if verdict.kind == "cap" and (agent is None or agent.status == "unknown"):
        return (Merged(owner, agent) if agent else None), None  # a cap limits optimism; it doesn't replace an open question
    opinion = agent is not None and agent.status != "unknown"
    said = f" The {agent_label} had said '{agent.status}': {agent.rationale}" if opinion else ""
    merged = AgentMetricAssessment(
        metric_id=mid, status=verdict.status, rationale=f"{verdict.rationale}{said}".strip(),
        evidence_ids=sorted({*(agent.evidence_ids if opinion else []), *verdict.evidence_ids}),
        facts=agent.facts if opinion else [], assumptions=agent.assumptions if opinion else [],
    )
    conflict = f"{agent_label} said '{agent.status}', but the {verdict.source} say '{verdict.status}'" if opinion and agent.status != verdict.status else None
    return Merged(owner, merged, overridden=True), conflict
