"""Neighborhood Agent: investigates the surroundings within a radius chosen for the user's purpose
(Vexcel neighbor parcels + OpenStreetMap places + Census demographics where available)."""
from __future__ import annotations

from collections import Counter
from statistics import mean

from agents.base import AgentReport, RunContext, ToolBudget, run_agent, tracked_tool
from config import place_groups
from services.vexcel import primary_structure

ROLE = (
    "You investigate the area around the selected building: who the likely customers are, what competes, "
    "how people get there and whether the surroundings fit the use. Judge the neighborhood through the lens "
    "of THIS business (a restaurant, gym, dental clinic and office need very different surroundings). "
    "Pick radii that match how far this business's customers travel."
)


def build_tools(ctx: RunContext, budget: ToolBudget) -> list:
    tool = tracked_tool(ctx, "neighborhood", budget, "OpenStreetMap (Overpass)")
    places = ctx.neighborhood.get("places", [])
    places_ok = any(src["name"].startswith("OpenStreetMap") and src["status"] == "used" for src in ctx.neighborhood.get("sources", []))
    groups_cfg = place_groups()
    UNAVAILABLE = {
        "summary": "Place data UNAVAILABLE (the OpenStreetMap request failed). Counts are unknown, NOT zero.",
        "data": None,
        "source": "OpenStreetMap (Overpass) — request failed",
        "guidance": ["Do not infer 'no competitors' or 'no demand' from this. Mark place-based metrics unknown or rely on Vexcel building mix and demographics, and list the gap in missing_information."],
    }
    roles = ctx.business.get("place_roles", {})
    max_r = 1500

    @tool
    def count_places(group: str, radius_m: int) -> dict:
        """Count places of one group within radius_m (100-1500) and list the nearest ones.
        Groups: food_drink, dental_medical, fitness, transit, parking, offices, lodging, education,
        entertainment, retail, residential_services."""
        if not places_ok:
            return UNAVAILABLE
        if group not in groups_cfg:
            return {"summary": f"Unknown group '{group}'. Valid: {', '.join(groups_cfg)}", "data": None}
        r = max(100, min(int(radius_m), max_r))
        hits = [p for p in places if p["group"] == group and p["distance_m"] <= r]
        nearest = [{"name": p["name"] or "(unnamed)", "category": p["category"], "distance_m": p["distance_m"], "brand": p.get("brand"), "cuisine": p.get("cuisine")} for p in hits[:8]]
        role = next((k for k, v in roles.items() if group in v), "context")
        return {
            "summary": f"{len(hits)} {groups_cfg[group]['label'].lower()} within {r} m (role for this business: {role})",
            "data": {"group": group, "radius_m": r, "count": len(hits), "role_for_business": role, "nearest": nearest, "named": sum(1 for p in hits if p["name"])},
            "source": "OpenStreetMap (Overpass)",
            "guidance": ["OpenStreetMap coverage is volunteer-mapped: counts are a lower bound, especially for small businesses."],
        }

    @tool
    def get_building_mix(radius_m: int) -> dict:
        """Vexcel building types, condition and activity around the property within radius_m."""
        r = max(100, min(int(radius_m), ctx.neighborhood.get("fetched_radius_m", 1500)))
        rows = []
        for f in ctx.neighbor_features:
            s = primary_structure(f) or {}
            d = f.get("_distance_m")
            if d is not None and d <= r:
                rows.append((s, f.get("properties", {})))
        mix = Counter((s.get("building-type.class") or "unknown") for s, _ in rows)
        conds = [s["roof-characteristics.condition"] for s, _ in rows if isinstance(s.get("roof-characteristics.condition"), (int, float))]
        vehicles = sum(p.get("vehicles.count") or 0 for _, p in rows)
        residential = sum(mix.get(t, 0) for t in ("single_family", "multiple_family", "condo_apartment", "mobile_home"))
        return {
            "summary": f"{len(rows)} buildings within {r} m: {', '.join(f'{k} {v}' for k, v in mix.most_common(4))}; avg roof condition {mean(conds):.1f}/5" if conds else f"{len(rows)} buildings within {r} m",
            "data": {"radius_m": r, "buildings": len(rows), "mix": dict(mix), "residential_buildings": residential, "avg_roof_condition": round(mean(conds), 2) if conds else None, "poor_roofs": sum(1 for c in conds if c <= 2), "vehicles_seen": vehicles},
            "source": "Vexcel /property/extract (neighbor parcels)",
            "guidance": ["Residential building counts are a proxy for nearby residents; multifamily/condo buildings hold many households each.", "Average roof condition hints at area investment/maintenance."],
        }

    @tool
    def get_access_options(radius_m: int = 400) -> dict:
        """Transit stops/stations and public parking within radius_m (default 400 m ≈ 5-minute walk)."""
        if not places_ok:
            return UNAVAILABLE
        r = max(100, min(int(radius_m), max_r))
        transit = [p for p in places if p["group"] == "transit" and p["distance_m"] <= r]
        parking = [p for p in places if p["group"] == "parking" and p["distance_m"] <= r]
        rail = [p for p in transit if p["category"].startswith("railway")]
        return {
            "summary": f"{len(transit)} transit stops ({len(rail)} rail) and {len(parking)} public parking facilities within {r} m",
            "data": {"radius_m": r, "transit_stops": len(transit), "rail_stations": len(rail), "nearest_transit_m": transit[0]["distance_m"] if transit else None, "public_parking": len(parking), "nearest_parking_m": parking[0]["distance_m"] if parking else None, "parking_names": [p["name"] for p in parking[:5] if p["name"]]},
            "source": "OpenStreetMap (Overpass)",
        }

    @tool
    def get_demographics() -> dict:
        """Census tract demographics (population, median household income, median age) for the property."""
        c = ctx.census or {}
        if c.get("acs"):
            return {"summary": f"Tract {c['tract']['name']}: population {c['acs'].get('population')}, median household income ${c['acs'].get('median_household_income')}", "data": c, "source": "US Census Bureau ACS 5-year", "url": "https://api.census.gov/data/2023/acs/acs5"}
        return {"summary": f"Demographics unavailable: {c.get('note') or 'no census data'}", "data": {"tract": c.get("tract"), "status": c.get("status")}, "source": "US Census Bureau", "guidance": ["Use residential building counts and demand-generator places as proxies, and flag demographics as missing."]}

    return [count_places, get_building_mix, get_access_options, get_demographics]


def task_prompt(ctx: RunContext, focus: str | None = None) -> str:
    roles = ctx.business.get("place_roles", {})
    groups = place_groups()
    role_lines = "\n".join(f"- {role}: {', '.join(f'{g} ({groups[g]['label']})' for g in gs)}" for role, gs in roles.items() if gs)
    places_ok = any(src["name"].startswith("OpenStreetMap") and src["status"] == "used" for src in ctx.neighborhood.get("sources", []))
    available = ", ".join(f"{k} {v}" for k, v in list(ctx.neighborhood.get("place_groups", {}).items())[:10]) if places_ok else "UNAVAILABLE (OpenStreetMap request failed; counts unknown, not zero)"
    base = (
        f"Investigate the neighborhood of the selected building for: \"{ctx.query}\".\n"
        f"Suggested catchment for a {ctx.business['label'].lower()}: {ctx.business['default_radius_m']} m — {ctx.business['radius_reason'].strip()} "
        f"(the user looked at {ctx.neighborhood.get('user_radius_m')} m). Choose radii per question: e.g. walking distance for access, the catchment for demand.\n"
        f"Place groups and what they mean for this business:\n{role_lines}\n"
        f"Places mapped within {ctx.neighborhood.get('user_radius_m')} m (overview): {available or 'none/unavailable'}.\n"
        "Investigate demand, competition, access and area fit; note where OpenStreetMap or missing demographics limit conclusions."
    )
    if focus:
        base += f"\n\nFOLLOW-UP FROM THE LEAD ENGINE: {focus}\nFocus only on resolving this; use at most 3 tool calls."
    return base


def quick_prefetch(ctx: RunContext) -> list[tuple[str, dict]]:
    """Demand and competition groups for this business at its catchment, plus access, mix and demographics."""
    radius = ctx.business["default_radius_m"]
    roles = ctx.business.get("place_roles", {})
    groups = [g for role in ("competitors", "demand") for g in roles.get(role, [])]
    calls = [("count_places", {"group": g, "radius_m": radius}) for g in dict.fromkeys(groups)]
    return calls + [("get_building_mix", {"radius_m": radius}), ("get_access_options", {"radius_m": 400}), ("get_demographics", {})]


async def run(ctx: RunContext, budget_limit: int = 7, focus: str | None = None) -> AgentReport:
    budget = ToolBudget(budget_limit)
    tools = build_tools(ctx, budget)
    if ctx.mode == "quick" and not focus:
        budget.limit = 20  # room for the pre-gathered calls; reset to used + 2 after prefetch
        return await run_agent(ctx, "neighborhood", ROLE, task_prompt(ctx), tools, budget, prefetch_calls=quick_prefetch(ctx), max_model_calls=3)
    return await run_agent(ctx, "neighborhood", ROLE, task_prompt(ctx, focus), tools, budget)
