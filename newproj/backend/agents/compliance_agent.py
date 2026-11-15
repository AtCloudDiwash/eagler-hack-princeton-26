"""Compliance Agent: investigates whether the intended use is allowed at this location and what
approvals it needs, using only the verified rule set (config/jurisdictions.yaml). It never claims a
property is compliant without evidence; unverified rules are reported as unknown with where to check."""
from __future__ import annotations

from agents.base import AgentReport, RunContext, ToolBudget, building_facts_result, run_agent, tracked_tool
from services import program as space_program
from services import rules
from services.vexcel import primary_structure, stories_estimate

ROLE = (
    "You investigate the regulations that apply to THIS address and THIS use: whether the use is permitted "
    "(zoning or its absence, deed/lease restrictions), parking minimums, health/food or medical rules, "
    "accessibility and occupancy permits. Only cite rules returned by your tools. Never invent a regulation "
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
        recorded = (ctx.building.get("facts") or {}).get("parking_spaces") or {}
        spaces = recorded.get("value") if recorded.get("source") == "CoStar" else None
        item = rules.parking_requirement(jur, ctx.intent["business_type"], leased_floor_sqft, ctx.property["lat"], ctx.property["lon"], parcel.get("hardscapes.area"), spaces)
        return {"summary": f"Parking: {item['status'].upper()} — {item['detail'][:180]}", "data": item, "source": item.get("citation") or "No verified source", "url": item.get("url")}

    @tool
    def list_use_requirements() -> dict:
        """Permits and code requirements this use triggers here (health/food, grease, X-ray, ADA, certificate of occupancy)."""
        items = rules.use_requirements(jur, ctx.intent["business_type"])
        return {"summary": f"{len(items)} requirements: {', '.join(i['rule'] for i in items)}", "data": {"items": items}, "source": jur["name"] + " verified rule set"}

    @tool
    def check_accessibility_signals() -> dict:
        """Physical signals relevant to accessibility: stories, elevators, year built and the listed suite's
        floor (CoStar building record), plus building type and stories from aerial data."""
        facts = ctx.building.get("facts") or {}

        def fv(fid: str):
            f = facts.get(fid) or {}
            return f.get("value") if f.get("source") == "CoStar" else None

        best = ctx.property.get("best_space") or {}
        data = {
            "stories": fv("stories"), "stories_source": "CoStar" if fv("stories") else "not recorded (aerial estimates are not accessibility evidence)",
            "elevators": fv("elevators"), "year_built": fv("year_built"), "building_type": s.get("building-type.class"),
            "listed_suite_floor": best.get("floor"), "listed_suite_ground_floor": best.get("ground_floor"),
        }
        pre_ada = isinstance(data["year_built"], int) and data["year_built"] < 1991
        bits = [f"{data['stories']} stories (CoStar)" if data["stories"] else "stories not recorded", f"elevators: {data['elevators'] if data['elevators'] is not None else 'not recorded'}"]
        if data["year_built"]:
            bits.append(f"built {data['year_built']}" + (" (before the 1991 ADA standards: expect upgrades)" if pre_ada else ""))
        if data["listed_suite_floor"]:
            bits.append(f"listed suite on the {str(data['listed_suite_floor']).lower()}")
        return {"summary": ", ".join(bits), "data": data, "source": "CoStar building record", "guidance": ["Only recorded data counts for accessibility. The engine sets accessibility_ada from the CoStar record and door widths measured in a scan verified to show the listed suite; without those it is 'unknown'. You may only be more cautious.", "Entrance step, ramps and restroom layout need a site visit."]}

    @tool
    def check_space_program() -> dict:
        """What the user's request triggers in the building code (occupancy group, occupant load, exits,
        restrooms, sprinklers, accessibility, timeline, stated needs) and how this building measures up."""
        p = ctx.program
        checks = space_program.site_checks(p, space_program.facts_from(ctx.property, ctx.feature, ctx.building))
        risks = [c for c in checks if c["status"] == "risk"]
        occ = p["occupancy"]
        return {
            "summary": f"~{occ['occupant_load']} occupants, Group {occ['group']}: " + "; ".join(f"{c['rule']} {c['value']}" for c in p["code"] if c["id"] in {"exits", "restrooms", "sprinklers"}) + (f". {len(risks)} building conflict(s): " + ", ".join(c["label"] for c in risks) if risks else ". No building conflicts found in the available data"),
            "data": {"occupancy": occ, "code": p["code"], "site_checks": checks, "needs": p["needs"], "timeline": p["timeline"]},
            "source": "IBC/IPC 2021 model code analysis of the user's program (services/program.py)",
            "guidance": [p["disclaimer"], "Statuses 'unknown' mean the building data cannot confirm it (e.g. a second exit, sprinklers); list them as questions for the landlord."],
        }

    @tool
    def get_building_facts(group: str = "site") -> dict:
        """Recorded facts from the CoStar building record: 'site' (zoning code, parking spaces, sprinklers),
        'building' (year built, stories, elevators, ceiling height) or 'space' (prior build-out)."""
        return building_facts_result(ctx, group)

    tools = [identify_jurisdiction, check_permitted_use, compute_parking_requirement, list_use_requirements, check_accessibility_signals, check_space_program]
    return [*tools, get_building_facts] if (ctx.building or {}).get("facts") else tools


def task_prompt(ctx: RunContext, focus: str | None = None) -> str:
    base = (
        f"Investigate the regulations for: \"{ctx.query}\" at {ctx.property.get('address') or 'the selected building'}.\n"
        f"Assumed leased floor area for this use: ~{ctx.target_sqft:,} sq ft ({ctx.target_basis}).\n"
        "Determine whether the intended use is permitted here, which approvals are required, and which "
        "requirements this specific site likely triggers or cannot yet confirm. Use check_space_program to see what "
        "the user's size, headcount and stated needs trigger (occupancy, exits, restrooms, sprinklers) at this building."
    )
    if focus:
        base += f"\n\nFOLLOW-UP FROM THE LEAD ENGINE: {focus}\nFocus only on resolving this; use at most 3 tool calls."
    return base


async def run(ctx: RunContext, budget_limit: int = 6, focus: str | None = None, metric_ids: list[str] | None = None) -> AgentReport:
    budget = ToolBudget(budget_limit, ctx.shared.setdefault("seen:compliance", {}))
    return await run_agent(ctx, "compliance", ROLE, task_prompt(ctx, focus), build_tools(ctx, budget), budget, metric_ids=metric_ids)
