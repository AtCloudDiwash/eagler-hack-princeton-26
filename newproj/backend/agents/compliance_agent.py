"""Compliance Agent: investigates whether the intended use is allowed at this location and what
approvals it needs, using only the verified rule set (config/jurisdictions.yaml). It never claims a
property is compliant without evidence; unverified rules are reported as unknown with where to check."""
from __future__ import annotations

from agents.base import AgentReport, RunContext, ToolBudget, run_agent, tracked_tool
from services import rules
from services.flood import SOURCE, flood_zone
from services.vexcel import primary_structure, stories_estimate

ROLE = (
    "You investigate the regulations that apply to THIS address and THIS use: whether the use is permitted "
    "(zoning or its absence, deed/lease restrictions), parking minimums, health/food or medical rules, "
    "accessibility, flood zone and occupancy permits. Only cite rules returned by your tools. Never invent a regulation "
    "and never call the property compliant unless a tool result supports it; otherwise say what must be verified and where."
)


def build_tools(ctx: RunContext, budget: ToolBudget) -> list:
    tool = tracked_tool(ctx, "compliance", budget, "Verified jurisdiction rule set")
    jur = ctx.jurisdiction
    feature = ctx.feature or {}
    parcel = feature.get("properties", {})
    s = primary_structure(feature) or {}

    @tool
    def identify_jurisdiction() -> dict:
        """Which city/state rules apply to this address and whether we have a verified rule set for it."""
        return {
            "summary": f"{ctx.property.get('city') or '?'}, {ctx.property.get('state') or '?'} → rule set '{jur['name']}' (zoning: {jur.get('zoning_mode')})",
            "data": {"address": ctx.property.get("address"), "city": ctx.property.get("city"), "state": ctx.property.get("state"), "rule_set": jur["name"], "rule_set_key": ctx.jurisdiction_key, "zoning_mode": jur.get("zoning_mode"), "verified": ctx.jurisdiction_key != "_default"},
            "source": "OpenStreetMap reverse geocode + verified rule set",
        }

    @tool
    def check_permitted_use() -> dict:
        """Is this business use permitted at the address (zoning or no-zoning rules, restriction caveats)?"""
        item = rules.permitted_use(jur, ctx.intent["business_type"])
        return {"summary": f"Permitted use: {item['status'].upper()} — {item['detail'][:160]}", "data": item, "source": item.get("citation") or "No verified source", "url": item.get("url")}

    @tool
    def compute_parking_requirement(leased_floor_sqft: int) -> dict:
        """Required off-street parking for the use at a given leased floor area, vs. paved area on the parcel."""
        item = rules.parking_requirement(jur, ctx.intent["business_type"], leased_floor_sqft, ctx.property["lat"], ctx.property["lon"], parcel.get("hardscapes.area"))
        return {"summary": f"Parking: {item['status'].upper()} — {item['detail'][:180]}", "data": item, "source": item.get("citation") or "No verified source", "url": item.get("url")}

    @tool
    def list_use_requirements() -> dict:
        """Permits and code requirements this use triggers here (health/food, grease, X-ray, ADA, certificate of occupancy)."""
        items = rules.use_requirements(jur, ctx.intent["business_type"])
        return {"summary": f"{len(items)} requirements: {', '.join(i['rule'] for i in items)}", "data": {"items": items}, "source": jur["name"] + " verified rule set"}

    @tool
    def check_accessibility_signals() -> dict:
        """Physical signals relevant to accessibility from aerial data (stories, entrance elevation, building type)."""
        data = {"stories_estimate": stories_estimate(s), "entrance_elevation": s.get("roof-characteristics.entrance-elevation"), "building_type": s.get("building-type.class"), "ground_elevation_ft": s.get("ground-elevation.value")}
        return {"summary": f"~{data['stories_estimate'] or '?'} stories, entrance elevation {data['entrance_elevation'] if data['entrance_elevation'] is not None else 'not measured'}", "data": data, "source": "Vexcel /property/extract", "guidance": ["Aerial data cannot confirm door widths, ramps or restroom layout; those need a site visit or Matterport scan."]}

    @tool
    def check_flood_zone() -> dict:
        """FEMA flood hazard zone at the address and the floodplain rules / insurance it triggers here."""
        item = rules.flood_item(jur, flood_zone(ctx.property["lat"], ctx.property["lon"]))
        return {"summary": f"Flood: {item['status'].upper()} — {item['detail'][:170]}", "data": item, "source": SOURCE, "url": item.get("url")}

    return [identify_jurisdiction, check_permitted_use, compute_parking_requirement, list_use_requirements, check_accessibility_signals, check_flood_zone]


def task_prompt(ctx: RunContext, focus: str | None = None) -> str:
    base = (
        f"Investigate the regulations for: \"{ctx.query}\" at {ctx.property.get('address') or 'the selected building'}.\n"
        f"Assumed leased floor area for this use: ~{ctx.target_sqft:,} sq ft ({ctx.target_basis}).\n"
        "Determine whether the intended use is permitted here, which approvals are required, and which "
        "requirements this specific site likely triggers or cannot yet confirm."
    )
    if focus:
        base += f"\n\nFOLLOW-UP FROM THE LEAD ENGINE: {focus}\nFocus only on resolving this; use at most 3 tool calls."
    return base


async def run(ctx: RunContext, budget_limit: int = 6, focus: str | None = None) -> AgentReport:
    budget = ToolBudget(budget_limit)
    tools = build_tools(ctx, budget)
    if ctx.mode == "quick" and not focus:
        calls = [
            ("identify_jurisdiction", {}),
            ("check_permitted_use", {}),
            ("compute_parking_requirement", {"leased_floor_sqft": ctx.target_sqft}),
            ("list_use_requirements", {}),
            ("check_accessibility_signals", {}),
            ("check_flood_zone", {}),
        ]
        return await run_agent(ctx, "compliance", ROLE, task_prompt(ctx), tools, budget, prefetch_calls=calls, extra_tool_calls=1, max_model_calls=3)
    return await run_agent(ctx, "compliance", ROLE, task_prompt(ctx, focus), tools, budget)
