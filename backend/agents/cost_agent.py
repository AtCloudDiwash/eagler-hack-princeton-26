"""Cost Agent: investigates financial feasibility. It decides which conversion items the evidence
triggers (citing it); the deterministic cost engine (services/costs.py) computes every number."""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import AgentReport, RunContext, ToolBudget, building_facts_result, run_agent, tracked_tool
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


NET_SERVICE = {"TripleNet", "Net", "DoubleNet"}  # the cost engine adds NNN charges itself, so only net rents fit


def _costar_rent(ctx: RunContext) -> dict | None:
    """The listed suite's asking rent, when it is a net rent the cost engine can use without double counting."""
    best = ctx.property.get("best_space") or {}
    rate = best.get("rent_per_sqft_yr")
    if not rate or best.get("service") not in NET_SERVICE:
        return None
    suite = f"Suite {best['suite']}" if best.get("suite") else "listed space"
    return {"per_sqft_low": rate, "per_sqft_high": rate, "source": f"CoStar listing, {suite}, {best['service']}"}


def _recorded_hint(ctx: RunContext) -> str:
    """One line of recorded CoStar facts that change the estimate (prior same-use build-out, CAM)."""
    facts = (ctx.building or {}).get("facts") or {}
    bits = []
    prior = facts.get("second_generation_use")
    if prior:
        same = prior["value"] in {"restaurant": {"restaurant"}, "medical_office": {"dental", "medical"}}.get(ctx.business["zoning_use"], set())
        bits.append(f"prior {prior['value']} build-out recorded ({prior['confidence']} confidence{', same use: consider second_generation=True' if same else ''})")
    if facts.get("prior_buildout_status"):
        bits.append(f"build-out status: {facts['prior_buildout_status']['value']}")
    if facts.get("cam_per_sqft_yr"):
        bits.append(f"listed CAM ${facts['cam_per_sqft_yr']['value']}/sq ft/yr")
    return ("CoStar record (cite via get_building_facts): " + "; ".join(bits) + ".\n") if bits else ""


def build_tools(ctx: RunContext, budget: ToolBudget) -> list:
    tool = tracked_tool(ctx, "cost", budget, "Deterministic cost engine (config/costs.yaml)")
    use = ctx.business["zoning_use"]

    @tool
    def get_rent_assumption() -> dict:
        """Rent for this space: the CoStar asking rent of a listed suite in the user's size range when there is one,
        otherwise the planning band for this use and city."""
        band = costs.rent_band(ctx.jurisdiction_key, ctx.intent["business_type"])
        listed = _costar_rent(ctx)
        data = {"planning_band": band, "costar_listing": ctx.property.get("best_space"), "costar_asking_range_all_spaces": ctx.property.get("asking_rent_per_sqft_yr"), "used_by_cost_engine": "costar" if listed else "planning band"}
        if listed:
            return {"summary": f"CoStar asking rent ${listed['per_sqft_low']}/sq ft/yr ({listed['source']}); planning band was ${band['per_sqft_low']}–{band['per_sqft_high']}", "data": data, "source": "CoStar lease listing (kit snapshot)"}
        note = f"; CoStar lists spaces here at ${ctx.property['asking_rent_per_sqft_yr'][0]}–{ctx.property['asking_rent_per_sqft_yr'][1]}/sq ft/yr but not on a net basis in your size range" if ctx.property.get("asking_rent_per_sqft_yr") else ""
        return {"summary": f"Rent ${band['per_sqft_low']}–{band['per_sqft_high']}/sq ft/yr NNN ({band['source']}){note}", "data": data}

    @tool
    def list_cost_items() -> dict:
        """Conversion cost items that can apply to this business, with their planning cost bands."""
        items = {k: {"label": v["label"], "unit": v["unit"], "low": v["low"], "high": v["high"]} for k, v in costs_config()["adders"].items() if use in v["applies_to"]}
        return {"summary": f"{len(items)} applicable cost items: {', '.join(items)}", "data": items}

    @tool
    def estimate_costs(leased_sqft: int, adders: list[CostAdder], second_generation: bool = False) -> dict:
        """Compute upfront and monthly cost ranges. adders = items the evidence triggers. second_generation=True
        only if evidence shows the space was already used for this business."""
        valid = ctx.visible_evidence("cost")
        cleaned = []
        for a in adders:
            a = a.model_dump() if isinstance(a, BaseModel) else dict(a)
            a["evidence_ids"] = [e for e in a.get("evidence_ids") or [] if e in valid]  # drop invented/"none" citations
            cleaned.append(a)
        rent = _costar_rent(ctx)
        result = costs.estimate(ctx.intent["business_type"], leased_sqft, ctx.jurisdiction_key, cleaned, second_generation, rent)
        result["sqft_basis"] = f"{leased_sqft:,} sq ft leased ({ctx.target_basis})"
        # Inputs kept (private "_" keys, not shown) so the engine can recompute at the program size if needed.
        result.update({"_adders": cleaned, "_second_generation": second_generation, "_rent_override": rent})
        status = costs.cost_status(result)
        return {
            "summary": f"Upfront ${result['upfront']['low']:,}–{result['upfront']['high']:,}; monthly ${result['monthly_occupancy']['low']:,}–{result['monthly_occupancy']['high']:,} (cost engine rates this '{status}' vs typical budgets)",
            "data": result,
        }

    @tool
    def get_building_facts(group: str = "space") -> dict:
        """Recorded facts from the CoStar building record: 'space' (prior build-out / second-generation use,
        CAM charges, available area) or 'building' (year built, renovations, condition). A prior same-use
        build-out is evidence for second_generation=True."""
        return building_facts_result(ctx, group)

    tools = [get_rent_assumption, list_cost_items, estimate_costs]
    return [*tools, get_building_facts] if (ctx.building or {}).get("facts") else tools


def task_prompt(ctx: RunContext, focus: str | None = None) -> str:
    upstream = ctx.shared.get("upstream_findings") or "(no upstream findings)"
    base = (
        f"Assess financial feasibility for: \"{ctx.query}\".\n"
        f"Space need: ~{ctx.target_sqft:,} sq ft ({ctx.target_basis}). Building footprint (not rentable area): {ctx.property.get('area_sqft') or 'unknown'} sq ft.\n"
        + (f"CoStar: rentable building area {(ctx.property.get('rentable_sqft') or 0):,.0f} sq ft ({ctx.property.get('rentable_basis') or 'n/a'}); {ctx.property.get('space_count') or 0} space(s) on the market" + (f"; best fit {ctx.property['best_space']['sqft']:,.0f} sq ft" if ctx.property.get('best_space') else "") + ". Use a listed space's size for leased_sqft when it fits the need.\n" if ctx.property.get("rentable_sqft") or ctx.property.get("space_count") else "")
        + (f"USER'S BUDGET: ${ctx.intent['budget']['amount']:,.0f} ({ctx.intent['budget']['period']}). Judge feasibility against it.\n" if ctx.intent.get("budget") else "The user did not state a budget; judge against typical budgets for this business.\n")
        + _recorded_hint(ctx)
        + f"Findings from other agents (cite their evidence ids when they trigger a cost):\n{upstream}\n\n"
        "Steps: check the rent assumption and available cost items, decide which items the evidence triggers "
        "(and which are uncertain), then call estimate_costs once with your chosen items. If an item depends on "
        "an unknown (e.g., HVAC not detected), include it as a contingency-style item and say it is an assumption."
    )
    if focus:
        base += f"\n\nFOLLOW-UP FROM THE LEAD ENGINE: {focus}"
    return base


async def run(ctx: RunContext, budget_limit: int = 5, focus: str | None = None, metric_ids: list[str] | None = None) -> AgentReport:
    budget = ToolBudget(budget_limit, ctx.shared.setdefault("seen:cost", {}))
    return await run_agent(ctx, "cost", ROLE, task_prompt(ctx, focus), build_tools(ctx, budget), budget, metric_ids=metric_ids)
