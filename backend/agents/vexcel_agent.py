"""Vexcel Agent: investigates the selected building from Vexcel aerial AI data, deciding which
building characteristics matter for the user's business and what the data cannot tell."""
from __future__ import annotations

from datetime import date
from statistics import mean
from typing import Literal

from agents.base import AgentReport, RunContext, ToolBudget, building_facts_result, deterministic_report, run_agent, tracked_tool
from config import roof_condition_labels
from schemas import AgentFinding, AgentMetricAssessment
from services.vexcel import FIELD_NOTES, primary_structure, stories_estimate
from services.verdicts import size_assessment

SOURCE = "Vexcel /property/extract (AI-detected from aerial imagery)"
ROLE = (
    "You examine the selected building using Vexcel's aerial AI data (roof, rooftop equipment, footprint, "
    "site paving). Decide which characteristics actually matter for the user's business, identify risks, "
    "and state clearly what aerial data cannot establish (interiors, leases, utilities)."
)


def build_tools(ctx: RunContext, budget: ToolBudget) -> list:
    tool = tracked_tool(ctx, "vexcel", budget, SOURCE)
    feature = ctx.feature or {}
    parcel = feature.get("properties", {})
    s = primary_structure(feature) or {}

    def pick(prefix: str) -> dict:
        return {k: v for k, v in s.items() if k.startswith(prefix) and v is not None and "wkt" not in k}

    @tool
    def get_building_overview() -> dict:
        """Building type, footprint, estimated stories and height, and structures on the parcel. Start here."""
        data = {
            "building_type": s.get("building-type.class"),
            "building_type_confidence": s.get("building-type.score"),
            "footprint_area_sqft": s.get("footprint.area"),
            "roof_height_ft": s.get("roof-characteristics.height"),
            "stories_estimate": stories_estimate(s),
            "structures_on_parcel": parcel.get("structure.count"),
        }
        recorded = ((ctx.building or {}).get("facts") or {}).get("stories") or {}
        if recorded.get("source") == "CoStar":
            data["stories_recorded"] = recorded["value"]  # CoStar beats roof height ÷ ~13 ft
        if (data["roof_height_ft"] or 0) and (data["footprint_area_sqft"] or 0) and parcel.get("parcel-source") == "Voronoi":
            data["parcel_note"] = "Parcel boundary is a synthetic (Voronoi) estimate; lot area and on-parcel paving are unreliable."
        stories = f"{data['stories_recorded']} stories (CoStar)" if data.get("stories_recorded") else f"~{data['stories_estimate'] or '?'} stories (estimate)"
        return {
            "summary": f"{data['building_type'] or 'unknown'} building, {data['footprint_area_sqft'] or '?'} sq ft footprint, {stories}",
            "data": data,
            "guidance": [FIELD_NOTES["building-type.class"], FIELD_NOTES["footprint.area"], FIELD_NOTES["roof-characteristics.height"]],
        }

    @tool
    def check_size_fit() -> dict:
        """Compare the user's space need (their program's size range) with this building: a CoStar-listed
        suite when there is one, otherwise the ground-floor footprint and stories. Uses the same thresholds
        as the engine's size verdict."""
        footprint = s.get("footprint.area")
        stories = stories_estimate(s) or 1
        if not footprint:
            return {"summary": "Footprint area unavailable; size fit cannot be computed", "data": None}
        total = footprint * stories
        leased = min(footprint, ctx.target_sqft * 3)
        ratio = footprint / ctx.target_sqft
        size = (ctx.program or {}).get("size") or {}
        target, lo, hi = size.get("target_sqft", ctx.target_sqft), size.get("min_sqft", round(ctx.target_sqft * 0.85)), size.get("max_sqft", round(ctx.target_sqft * 1.3))
        p = ctx.property
        assessed = size_assessment(target, lo, hi, best_space=p.get("best_space"), space_count=p.get("space_count") or 0, available_sqft=p.get("available_sqft"),
                                   footprint_sqft=footprint, stories=stories, ground_floor_required=((ctx.program or {}).get("building") or {}).get("ground_floor") == "required")
        verdict = f"{assessed[0]} — {assessed[1]}" if assessed else "unknown"
        return {
            "summary": f"Ground floor {footprint:,.0f} sq ft vs need ~{ctx.target_sqft:,} sq ft ({ratio:.1f}x): {verdict}",
            "data": {
                "need_sqft": ctx.target_sqft,
                "need_basis": ctx.target_basis,
                "ground_floor_sqft": round(footprint),
                "estimated_total_floor_area_sqft": round(total),
                "stories_estimate": stories,
                "ratio_ground_floor_to_need": round(ratio, 2),
                "assumed_leased_sqft": round(leased),
                "ideal_range_sqft": [ctx.business["sizing"]["ideal_min_sqft"], ctx.business["sizing"]["ideal_max_sqft"]],
                "program_range_sqft": [lo, hi],
                "size_verdict": assessed[0] if assessed else None,
            },
            "guidance": ["Ground-floor space matters for customer-facing uses; upper floors rarely suit restaurants or gyms.", FIELD_NOTES["footprint.area"]],
        }

    @tool
    def inspect_roof(focus: Literal["condition", "defects", "equipment"]) -> dict:
        """Roof details. focus='condition' (score, material, shape), 'defects' (ponding, patches, tarps,
        structural damage) or 'equipment' (rooftop AC units, vents, solar, skylights)."""
        if focus == "condition":
            cond = s.get("roof-characteristics.condition.precise-value") or s.get("roof-characteristics.condition")
            data = {**pick("roof-characteristics.condition"), **pick("roof-characteristics.material"), **pick("roof-characteristics.shape")}
            label = roof_condition_labels().get(int(cond)) if isinstance(cond, (int, float)) else None
            return {"summary": f"Roof condition {cond}/5 ({label}), {s.get('roof-characteristics.material.class')} {s.get('roof-characteristics.shape.value')} roof", "data": data, "guidance": [FIELD_NOTES["roof-characteristics.condition"], FIELD_NOTES["roof-characteristics.shape.value"]]}
        if focus == "defects":
            data = {k: v for k, v in pick("roof-defects").items() if v not in (False, 0, 0.0)}  # ~45 keys, mostly "not detected"
            found = sorted({k.split(".")[1] for k, v in data.items() if k.endswith(".detected") and v is True and k.count(".") == 2})
            return {"summary": f"Roof defects detected: {', '.join(found) or 'none'}", "data": data, "guidance": [FIELD_NOTES["roof-defects"]]}
        data = pick("roof-objects")
        return {
            "summary": f"Rooftop: {s.get('roof-objects.ac-unit.count')} AC units detected, {s.get('roof-objects.roof-vent.count')} vents, solar {'yes' if (s.get('roof-objects.solar-panel-photovoltaic.count') or 0) > 0 else 'not detected'}, {s.get('roof-objects.skylight.count')} skylights",
            "data": data,
            "guidance": [FIELD_NOTES["roof-objects.ac-unit.count"], FIELD_NOTES["roof-objects.roof-vent.count"]],
        }

    @tool
    def inspect_site_paving() -> dict:
        """Parcel paving and vehicles: a proxy for on-site parking capacity and activity."""
        paved = parcel.get("hardscapes.area")
        data = {"hardscape_area_sqft": paved, "hardscape_percent": parcel.get("hardscapes.percent"), "vehicles_seen": parcel.get("vehicles.count"), "estimated_spaces_if_all_paving_were_parking": round(paved / 325) if isinstance(paved, (int, float)) else None, "tree_cover_percent": parcel.get("parcel-tree-cover.percent")}
        return {"summary": f"Paved area {paved or '?'} sq ft (≈{data['estimated_spaces_if_all_paving_were_parking'] or '?'} spaces max), {data['vehicles_seen'] or 0} vehicles seen", "data": data, "guidance": [FIELD_NOTES["hardscapes.area"], FIELD_NOTES["vehicles.count"]]}

    @tool
    def compare_with_neighbors(attribute: Literal["roof_condition", "footprint_area", "ac_units"]) -> dict:
        """How this building compares with surrounding buildings on one attribute (percentile)."""
        key = {"roof_condition": "roof-characteristics.condition", "footprint_area": "footprint.area", "ac_units": "roof-objects.ac-unit.count"}[attribute]
        values = []
        for f in ctx.neighbor_features:
            ns = primary_structure(f) or {}
            if isinstance(ns.get(key), (int, float)):
                values.append(ns[key])
        mine = s.get(key)
        if not values or not isinstance(mine, (int, float)):
            return {"summary": f"Not enough data to compare {attribute}", "data": {"this_building": mine, "neighbors": len(values)}}
        pct = round(100 * sum(1 for v in values if v <= mine) / len(values))
        return {"summary": f"{attribute}: this building {mine} vs neighbor avg {mean(values):.1f} (percentile {pct} of {len(values)})", "data": {"this_building": mine, "neighbor_average": round(mean(values), 2), "percentile": pct, "neighbors": len(values)}}

    @tool
    def get_imagery_metadata() -> dict:
        """When and how the imagery behind this data was captured (freshness and resolution)."""
        d = (parcel.get("metadata.ortho-date-estimate") or "")[:10]
        age = None
        if d:
            y, m, _ = (int(x) for x in d.split("-"))
            today = date.today()
            age = (today.year - y) * 12 + today.month - m
        return {"summary": f"Imagery {parcel.get('metadata.collection')} captured ~{d or '?'} ({age if age is not None else '?'} months ago), {parcel.get('metadata.gsd')} m/px", "data": {"collection": parcel.get("metadata.collection"), "capture_estimate": d, "age_months": age, "gsd_m": parcel.get("metadata.gsd")}, "guidance": [FIELD_NOTES["metadata.ortho-date-estimate"]]}

    @tool
    def lookup_vexcel_field(field: str) -> dict:
        """Read any raw Vexcel field by exact name or prefix (e.g. 'roof-defects.discoloration', 'pool', 'defensible-space')."""
        hits = {k: v for k, v in {**parcel, **s}.items() if k.startswith(field) and k != "structures" and "wkt" not in k}
        return {"summary": f"{len(hits)} fields matching '{field}'", "data": hits or None}

    @tool
    def get_building_facts(group: Literal["building", "site", "space"]) -> dict:
        """Recorded facts from the CoStar building record: 'building' (year built, renovations, class, condition,
        stories, ceiling height, elevators), 'site' (parking spaces, zoning, sprinklers) or 'space' (prior
        build-out / second-generation use, CAM). Recorded data beats aerial inference."""
        return building_facts_result(ctx, group)

    tools = [get_building_overview, check_size_fit, inspect_roof, inspect_site_paving, compare_with_neighbors, get_imagery_metadata, lookup_vexcel_field]
    return [*tools, get_building_facts] if (ctx.building or {}).get("facts") else tools


def task_prompt(ctx: RunContext, focus: str | None = None) -> str:
    p = ctx.property
    base = (
        f"Investigate the selected building at {p.get('address') or f'{p['lat']:.5f}, {p['lon']:.5f}'} "
        f"for this purpose: \"{ctx.query}\".\n"
        "Decide which building characteristics matter most for this business, gather evidence with your tools, "
        "probe anything surprising, and report risks and what aerial data cannot answer."
    )
    if focus:
        base += f"\n\nFOLLOW-UP FROM THE LEAD ENGINE: {focus}\nFocus only on resolving this; use at most 3 tool calls."
    return base


async def run(ctx: RunContext, budget_limit: int = 7, focus: str | None = None, metric_ids: list[str] | None = None) -> AgentReport:
    if not ctx.feature:
        return _no_vexcel_report(ctx)
    budget = ToolBudget(budget_limit, ctx.shared.setdefault("seen:vexcel", {}))
    return await run_agent(ctx, "vexcel", ROLE, task_prompt(ctx, focus), build_tools(ctx, budget), budget, metric_ids=metric_ids)


def _no_vexcel_report(ctx: RunContext) -> AgentReport:
    """No Vexcel data: assess only what the OpenStreetMap footprint supports (size), everything else unknown."""
    assessments, findings = [], []
    area = ctx.property.get("area_sqft")
    if area:
        ratio = area / ctx.target_sqft
        status = "strong" if 0.85 <= ratio <= 3 else "adequate" if ratio > 3 else "weak"
        eid = ctx.evidence.add(
            "vexcel", "check_size_fit", "OpenStreetMap building footprint (no Vexcel data)",
            f"OSM footprint {area:,.0f} sq ft vs need ~{ctx.target_sqft:,} sq ft ({ratio:.1f}x)",
            {"footprint_sqft": area, "need_sqft": ctx.target_sqft, "need_basis": ctx.target_basis, "ratio": round(ratio, 2), "source": "OpenStreetMap"},
        )
        ctx.emit("vexcel", "tool_result", f"{eid}: size fit from OpenStreetMap footprint ({ratio:.1f}x the need)", {"evidence_id": eid})
        assessments.append(AgentMetricAssessment(
            metric_id="size_fit", status=status, evidence_ids=[eid],
            rationale=f"OpenStreetMap footprint of {area:,.0f} sq ft is {ratio:.1f}x the ~{ctx.target_sqft:,} sq ft need. Footprint is mapped, not measured; stories and usable area are unverified.",
            facts=[f"OSM footprint {area:,.0f} sq ft"], assumptions=["Ground floor ≈ footprint; leasable share unknown"],
        ))
    covered = {a.metric_id for a in assessments}
    assessments += [AgentMetricAssessment(metric_id=m["id"], status="unknown", rationale="No Vexcel property data for this building (outside the key's coverage).") for m in ctx.metrics_for("vexcel") if m["id"] not in covered]
    findings.append(AgentFinding(title="No aerial property data", detail="Vexcel has no data for this building, so roof, rooftop HVAC and site paving are unknown; only the OpenStreetMap footprint was usable.", impact="negative", severity="medium", kind="fact", why_it_matters="Building-condition and infrastructure signals are missing, which lowers confidence."))
    ctx.emit("vexcel", "skipped", "No Vexcel data: assessed size from the OpenStreetMap footprint only", None)
    return deterministic_report(ctx, "vexcel", "No Vexcel data for this building; size was estimated from its OpenStreetMap footprint and all other building characteristics are unknown.", assessments, findings, ["Roof condition, rooftop HVAC and site paving are unknown without Vexcel data."])
