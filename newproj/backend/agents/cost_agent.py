"""Cost Agent: investigates financial feasibility. It decides which conversion items the evidence
triggers (citing it); the deterministic cost engine (services/costs.py) computes every number."""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import AgentReport, RunContext, ToolBudget, run_agent, tracked_tool
from config import costs_config
from services import costs

ROLE = (
    "You investigate whether the selected property is financially feasible for the user's business. "
    "Use the other agents' findings to decide which conversion items apply (e.g., a hood for a restaurant "
    "without known exhaust, roof repair for a poor roof, operatory plumbing for a dental clinic) and cite the "
    "evidence that triggers each. Never invent prices: all numbers come from the estimate_costs tool, which "
    "returns ranges with documented assumptions."
)


class CostAdder(BaseModel):
    id: str = Field(description="Cost item id from list_cost_items")
    quantity: int = Field(default=1, description="Number of units (e.g., HVAC units, operatories)")
    reason: str = Field(description="Why this item applies, tied to evidence")
    evidence_ids: list[str] = Field(default_factory=list, description="Evidence ids that trigger this item")


def build_tools(ctx: RunContext, budget: ToolBudget) -> list:
    tool = tracked_tool(ctx, "cost", budget, "Deterministic cost engine (config/costs.yaml)")
    use = ctx.business["zoning_use"]

    @tool
    def get_rent_assumption() -> dict:
        """Asking-rent band for this use and city (planning assumption; listing rents are not connected)."""
        band = costs.rent_band(ctx.jurisdiction_key, ctx.intent["business_type"])
        return {"summary": f"Rent ${band['per_sqft_low']}–{band['per_sqft_high']}/sq ft/yr NNN ({band['source']})", "data": band}

    @tool
    def list_cost_items() -> dict:
        """Conversion cost items that can apply to this business, with their planning cost bands."""
        items = {k: {"label": v["label"], "unit": v["unit"], "low": v["low"], "high": v["high"]} for k, v in costs_config()["adders"].items() if use in v["applies_to"]}
        return {"summary": f"{len(items)} applicable cost items: {', '.join(items)}", "data": items}

    @tool
    def estimate_costs(leased_sqft: int, adders: list[CostAdder], second_generation: bool = False) -> dict:
        """Compute upfront and monthly cost ranges. adders = items the evidence triggers. second_generation=True
        only if evidence shows the space was already used for this business."""
        valid = ctx.evidence.ids()
        cleaned = []
        for a in adders:
            a = a.model_dump() if isinstance(a, BaseModel) else dict(a)
            a["evidence_ids"] = [e for e in a.get("evidence_ids") or [] if e in valid]  # drop invented/"none" citations
            cleaned.append(a)
        result = costs.estimate(ctx.intent["business_type"], leased_sqft, ctx.jurisdiction_key, cleaned, second_generation)
        result["sqft_basis"] = f"{leased_sqft:,} sq ft leased ({ctx.target_basis})"
        status = costs.cost_status(result)
        return {
            "summary": f"Upfront ${result['upfront']['low']:,}–{result['upfront']['high']:,}; monthly ${result['monthly_occupancy']['low']:,}–{result['monthly_occupancy']['high']:,} (cost engine rates this '{status}' vs typical budgets)",
            "data": result,
        }

    return [get_rent_assumption, list_cost_items, estimate_costs]


def task_prompt(ctx: RunContext, focus: str | None = None) -> str:
    upstream = ctx.shared.get("upstream_findings") or "(no upstream findings)"
    base = (
        f"Assess financial feasibility for: \"{ctx.query}\".\n"
        f"Space need: ~{ctx.target_sqft:,} sq ft ({ctx.target_basis}). Building footprint: {ctx.property.get('area_sqft') or 'unknown'} sq ft.\n"
        + (f"USER'S BUDGET: ${ctx.intent['budget']['amount']:,.0f} ({ctx.intent['budget']['period']}). Judge feasibility against it.\n" if ctx.intent.get("budget") else "The user did not state a budget; judge against typical budgets for this business.\n")
        + f""
        f"Findings from other agents (cite their evidence ids when they trigger a cost):\n{upstream}\n\n"
        "Steps: check the rent assumption and available cost items, decide which items the evidence triggers "
        "(and which are uncertain), then call estimate_costs once with your chosen items. If an item depends on "
        "an unknown (e.g., HVAC not detected), include it as a contingency-style item and say it is an assumption."
    )
    if focus:
        base += f"\n\nFOLLOW-UP FROM THE LEAD ENGINE: {focus}"
    return base


def _latest(ctx: RunContext, tool: str, predicate=lambda d: True) -> tuple[str, dict] | None:
    for e in reversed(ctx.evidence.all()):
        if e.tool == tool and isinstance(e.data, dict) and predicate(e.data):
            return e.id, e.data
    return None


def pick_adders(ctx: RunContext) -> list[dict]:
    """Quick mode: choose conversion items deterministically from the evidence other agents gathered.
    Every item cites the evidence that triggered it; unverified conditions are labelled as allowances."""
    use = ctx.business["zoning_use"]
    out: list[dict] = []
    roof_eq = _latest(ctx, "inspect_roof", lambda d: any("ac-unit" in k for k in d))
    roof_cond = _latest(ctx, "inspect_roof", lambda d: any("condition" in k for k in d))
    parking = _latest(ctx, "compute_parking_requirement")
    reqs = _latest(ctx, "list_use_requirements")
    req_ids = {i["id"] for i in (reqs[1].get("items", []) if reqs else [])}
    ac_units = None
    if roof_eq:
        ac_units = next((v for k, v in roof_eq[1].items() if k.endswith("ac-unit.count")), None)

    def add(item: str, reason: str, evidence: tuple[str, dict] | None, quantity: int = 1) -> None:
        out.append({"id": item, "quantity": quantity, "reason": reason, "evidence_ids": [evidence[0]] if evidence else []})

    if use == "restaurant":
        add("hood_exhaust", "Commercial kitchen exhaust is required and no existing hood is verified (allowance).", roof_eq)
        if "grease_interceptor" in req_ids:
            add("grease_interceptor", "Food service requires a grease interceptor.", reqs)
    if ac_units in (0, None):
        add("hvac_rtu", "No rooftop AC units detected; HVAC capacity unverified (allowance).", roof_eq)
    if roof_cond:
        cond = next((v for k, v in roof_cond[1].items() if k.endswith("condition") or k.endswith("precise-value")), None)
        if isinstance(cond, (int, float)) and cond <= 2.5:
            add("roof_repair", f"Roof condition {cond}/5 suggests repair before fit-out.", roof_cond)
    if parking and parking[1].get("status") == "risk":
        add("parking_agreement", "Likely parking shortfall vs the city minimum.", parking)
    if use in {"restaurant", "medical_office", "gym", "retail", "office"} and req_ids & {"ada_tas", "ada_cbc11b", "ada"}:
        add("ada_upgrades", "Public-facing use: budget for accessible entry/restrooms (allowance).", reqs)
    if use == "medical_office":
        add("operatory_plumbing", "Each operatory needs water, vacuum and air.", None, quantity=max(3, round(ctx.target_sqft / 500)))
        add("electrical_upgrade", "Dental equipment needs dedicated circuits (allowance).", None)
    if use == "gym":
        add("rubber_flooring", "Free-weight areas need impact flooring.", None)
        add("locker_showers", "Members expect locker rooms with showers.", None)
    return out


async def run(ctx: RunContext, budget_limit: int = 5, focus: str | None = None) -> AgentReport:
    budget = ToolBudget(budget_limit)
    tools = build_tools(ctx, budget)
    if ctx.mode == "quick" and not focus:
        calls = [
            ("get_rent_assumption", {}),
            ("estimate_costs", {"leased_sqft": ctx.target_sqft, "adders": pick_adders(ctx), "second_generation": False}),
        ]
        task = task_prompt(ctx) + (
            "\n\nQUICK MODE: the estimate below already uses conversion items chosen from the evidence. Review whether "
            "they fit this business and budget and explain the result; call estimate_costs again only if an item is clearly wrong."
        )
        return await run_agent(ctx, "cost", ROLE, task, tools, budget, prefetch_calls=calls, extra_tool_calls=1, max_model_calls=3)
    return await run_agent(ctx, "cost", ROLE, task_prompt(ctx, focus), tools, budget)
