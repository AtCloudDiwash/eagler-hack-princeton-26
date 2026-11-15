"""Cost Agent: investigates financial feasibility. It decides which conversion items the evidence
triggers (citing it); the deterministic cost engine (services/costs.py) computes every number."""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.base import AgentReport, RunContext, ToolBudget, building_facts_result, run_agent, tracked_tool
from config import costs_config
from services import costs
from services.geo import haversine_m, outer_ring, point_in_polygon

PRIOR_USE_RADIUS_M = 30  # a mapped business this close to the building is treated as being in it

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

    @tool
    def check_prior_use() -> dict:
        """Is this building already used for the same kind of business (OpenStreetMap places in or at the
        building)? A second-generation space usually has the kitchen / plumbing / fit-out already in place."""
        found = prior_use(ctx)
        if found is None:
            return {"summary": "Prior use unknown: nearby-place data unavailable", "data": None, "source": "OpenStreetMap (Overpass)"}
        names = ", ".join(f"{p['name'] or p['category']} ({p['distance_m']} m)" for p in found[:3])
        return {
            "summary": f"Same kind of business already at this building: {names}" if found else "No same-kind business mapped at this building",
            "data": {"second_generation_likely": bool(found), "places": found[:5]},
            "source": "OpenStreetMap (Overpass)",
            "guidance": ["OpenStreetMap can be out of date; confirm the existing kitchen/plumbing with the landlord before relying on it."],
        }

    tools = [get_rent_assumption, list_cost_items, check_prior_use, estimate_costs]
    return [*tools, get_building_facts] if (ctx.building or {}).get("facts") else tools


def prior_use(ctx: RunContext) -> list[dict] | None:
    """Same-kind businesses (this business's competitor place groups) inside the footprint or within ~30 m.
    None when place data is unavailable (unknown, not 'no prior use')."""
    sources = ctx.neighborhood.get("sources", [])
    if not any(s["name"].startswith("OpenStreetMap") and s["status"] == "used" for s in sources):
        return None
    groups = set(ctx.business.get("place_roles", {}).get("competitors", []))
    if not groups:
        return []
    ring = outer_ring(ctx.property.get("footprint"))
    lat, lon = ctx.property["lat"], ctx.property["lon"]
    hits = []
    for p in ctx.neighborhood.get("places", []):
        if p["group"] not in groups:
            continue
        inside = bool(ring) and point_in_polygon(p["lon"], p["lat"], ring)
        d = haversine_m(lat, lon, p["lat"], p["lon"])
        if inside or d <= PRIOR_USE_RADIUS_M:
            hits.append({"name": p.get("name"), "category": p["category"], "distance_m": round(d), "inside_footprint": inside})
    return sorted(hits, key=lambda h: h["distance_m"])


def task_prompt(ctx: RunContext, focus: str | None = None) -> str:
    upstream = ctx.shared.get("upstream_findings") or "(no upstream findings)"
    base = (
        f"Assess financial feasibility for: \"{ctx.query}\".\n"
        f"Space need: ~{ctx.target_sqft:,} sq ft ({ctx.target_basis}). Building footprint (not rentable area): {ctx.property.get('area_sqft') or 'unknown'} sq ft.\n"
        + (f"CoStar: rentable building area {(ctx.property.get('rentable_sqft') or 0):,.0f} sq ft ({ctx.property.get('rentable_basis') or 'n/a'}); {ctx.property.get('space_count') or 0} space(s) on the market" + (f"; best fit {ctx.property['best_space']['sqft']:,.0f} sq ft" if ctx.property.get('best_space') else "") + ". Use a listed space's size for leased_sqft when it fits the need.\n" if ctx.property.get("rentable_sqft") or ctx.property.get("space_count") else "")
        + ("USER'S BUDGET: " + " and ".join(f"${b['amount']:,.0f} {b['period']}" for b in costs.user_budgets(ctx.intent)) + ". Judge feasibility against each.\n"
           if costs.user_budgets(ctx.intent) else "The user did not state a budget; judge against typical budgets for this business.\n")
        + _recorded_hint(ctx)
        + f"Findings from other agents (cite their evidence ids when they trigger a cost):\n{upstream}\n\n"
        "Steps: check the rent assumption, whether the building already hosts this kind of business (check_prior_use: "
        "a second-generation space keeps much of its fit-out), and the available cost items; decide which items the evidence triggers "
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

    second_gen = bool(prior_use(ctx))
    if use == "restaurant" and not second_gen:  # a second-generation restaurant usually keeps its hood and interceptor
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
    if use == "gym" and not second_gen:
        add("rubber_flooring", "Free-weight areas need impact flooring.", None)
        add("locker_showers", "Members expect locker rooms with showers.", None)
    return out




async def run(ctx: RunContext, budget_limit: int = 5, focus: str | None = None, metric_ids: list[str] | None = None) -> AgentReport:
    budget = ToolBudget(budget_limit, ctx.shared.setdefault("seen:cost", {}))
    tools = build_tools(ctx, budget)
    if ctx.mode == "quick" and not focus:
        calls = [
            ("get_rent_assumption", {}),
            ("check_prior_use", {}),
            ("estimate_costs", {"leased_sqft": ctx.target_sqft, "adders": pick_adders(ctx), "second_generation": bool(prior_use(ctx))}),
        ]
        task = task_prompt(ctx) + (
            "\n\nQUICK MODE: the estimate below already uses conversion items chosen from the evidence. Review whether "
            "they fit this business and budget and explain the result; call estimate_costs again only if an item is clearly wrong."
        )
        return await run_agent(ctx, "cost", ROLE, task, tools, budget, metric_ids=metric_ids, prefetch_calls=calls, extra_tool_calls=1, max_model_calls=3)
    return await run_agent(ctx, "cost", ROLE, task_prompt(ctx, focus), tools, budget, metric_ids=metric_ids)
