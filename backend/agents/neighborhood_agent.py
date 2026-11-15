"""Neighborhood Agent: investigates the surroundings within a radius chosen for the user's purpose.

Data: Vexcel neighbor parcels, OpenStreetMap places, Census LODES (daytime workers + employed residents per
block), a public walking router, and Census ACS tract demographics when a key is configured.

Tools are situational: besides the four base tools, the extra signals offered depend on the business type
(config/business_types.yaml -> neighborhood.signals) plus anything the user's request asks about
("foot traffic" -> daytime workers, "walkable" -> walking reach...). Fewer, relevant tools keep the prompt
short and avoid calls that can't change the answer.
"""
from __future__ import annotations

import re
from collections import Counter
from statistics import mean

from agents.base import AgentReport, RunContext, ToolBudget, run_agent, tracked_tool
from config import place_groups, settings
from services import lodes, walking
from services.vexcel import primary_structure

ROLE = (
    "You investigate the area around the selected building: who the likely customers are, what competes, "
    "how people get there and whether the surroundings fit the use. Judge the neighborhood through the lens "
    "of THIS business (a restaurant, gym, dental clinic and office need very different surroundings). "
    "Pick radii that match how far this business's customers travel. Prefer measured signals (daytime workers, "
    "residents, direct competitors, walking reach) over raw place counts when they are available."
)

LODES_SOURCE = "U.S. Census LEHD LODES"
LODES_URL = "https://lehd.ces.census.gov/data/"

# Words in the user's request that make an extra signal relevant even if the business config doesn't list it.
NEED_SIGNALS: dict[str, tuple[str, ...]] = {
    "daytime_workers": ("foot traffic", "walk-in", "walk in", "lunch", "office workers", "workers", "busy", "pedestrian", "daytime"),
    "residents": ("resident", "residential", "neighborhood", "families", "family", "affluent", "income", "wealthy", "locals", "community"),
    "walk_access": ("walkable", "walkability", "walking", "transit", "metro", "bus", "train", "rail", "pedestrian"),
    "competitors": ("competition", "competitor", "saturated", "saturation", "few restaurants", "no other"),
}

# User words -> OpenStreetMap values, to find same-kind competitors (cuisine for food, shop type for retail).
CUISINE_WORDS = {
    "mexican": ["mexican", "tex-mex"], "tex-mex": ["tex-mex", "mexican"], "taco": ["mexican", "tacos"], "italian": ["italian"],
    "pizza": ["pizza"], "chinese": ["chinese"], "japanese": ["japanese"], "sushi": ["sushi", "japanese"], "ramen": ["ramen", "japanese"],
    "thai": ["thai"], "indian": ["indian"], "vietnamese": ["vietnamese"], "pho": ["vietnamese"], "korean": ["korean"],
    "mediterranean": ["mediterranean", "greek", "lebanese"], "greek": ["greek"], "burger": ["burger"], "bbq": ["barbecue", "bbq"],
    "barbecue": ["barbecue", "bbq"], "seafood": ["seafood"], "steak": ["steak_house"], "coffee": ["coffee_shop"], "cafe": ["coffee_shop"],
    "vegan": ["vegan"], "chicken": ["chicken"], "sandwich": ["sandwich"], "breakfast": ["breakfast"], "brunch": ["breakfast", "brunch"],
    "donut": ["donut"], "ice cream": ["ice_cream"], "dessert": ["dessert", "ice_cream"], "american": ["american"], "cajun": ["cajun"],
}
SHOP_WORDS = {
    "clothing": ["clothes"], "clothes": ["clothes"], "boutique": ["clothes", "boutique"], "apparel": ["clothes"], "shoe": ["shoes"],
    "book": ["books"], "electronics": ["electronics"], "phone": ["mobile_phone"], "florist": ["florist"], "flower": ["florist"],
    "jewelry": ["jewelry"], "furniture": ["furniture"], "hardware": ["hardware", "doityourself"], "cosmetic": ["cosmetics", "beauty"],
    "beauty": ["beauty", "cosmetics"], "convenience": ["convenience"], "grocery": ["supermarket", "convenience"], "pharmacy": ["chemist"],
    "gift": ["gift"], "toy": ["toys"], "sport": ["sports"], "pet": ["pet"], "bike": ["bicycle"], "bicycle": ["bicycle"],
    "bakery": ["bakery"], "liquor": ["alcohol"], "wine": ["wine", "alcohol"], "thrift": ["second_hand"], "vape": ["e-cigarette"],
}


def request_text(ctx: RunContext) -> str:
    return " ".join([ctx.query or "", ctx.extra_requirements or "", *(ctx.intent.get("requirements") or [])]).lower()


def select_signals(ctx: RunContext) -> tuple[list[str], dict[str, str]]:
    """Signals to offer, and why each was chosen (business config or the user's words)."""
    cfg = (ctx.business.get("neighborhood") or {}).get("signals") or []
    why = {s: f"relevant for a {ctx.business['label'].lower()}" for s in cfg}
    text = request_text(ctx)
    for sig, words in NEED_SIGNALS.items():
        hit = next((w for w in words if w in text), None)
        if hit and sig not in why:
            why[sig] = f"you mentioned “{hit}”"
    if "competitors" in why and not (ctx.business.get("neighborhood") or {}).get("competitors"):
        why.pop("competitors")  # no rule for what a direct competitor is (e.g. an office)
    return list(why), why


def detect_kind(ctx: RunContext) -> tuple[str | None, list[str]]:
    """(the user's word, matching OSM values) for same-kind competition, e.g. ("mexican", ["mexican", "tex-mex"])."""
    kind_by = ((ctx.business.get("neighborhood") or {}).get("competitors") or {}).get("kind_by")
    table = CUISINE_WORDS if kind_by == "cuisine" else SHOP_WORDS if kind_by == "shop" else {}
    text = request_text(ctx)
    for word, values in table.items():
        if re.search(rf"\b{re.escape(word)}", text):
            return word, values
    return None, []


def _benchmark(ctx: RunContext, key: str, value: int, radius_m: int) -> str | None:
    """'strong' / 'moderate' / 'weak' against the business's planning heuristic, scaled by area to radius_m."""
    b = ((ctx.business.get("neighborhood") or {}).get("benchmarks") or {}).get(key)
    if not b:
        return None
    scale = (radius_m / ctx.business["default_radius_m"]) ** 2
    strong, weak = b["strong"] * scale, b["weak"] * scale
    band = "strong" if value >= strong else "weak" if value < weak else "moderate"
    return f"{band} for a {ctx.business['label'].lower()} (planning heuristic at {radius_m} m: strong ≥{strong:,.0f}, weak <{weak:,.0f})"


def _matches(place: dict, rule: dict) -> bool:
    tag, _, value = (place.get("category") or "").partition("=")
    allowed = rule.get(tag)
    return bool(allowed) and ("*" in allowed or value in allowed)


def build_tools(ctx: RunContext, budget: ToolBudget, signals: list[str] | None = None) -> list:
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
    lat, lon = ctx.property["lat"], ctx.property["lon"]
    state = ctx.property.get("state")
    signals = select_signals(ctx)[0] if signals is None else signals

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

    # ---------------------------------------------------------------- situational signals

    @tool
    def get_daytime_workers(radius_m: int) -> dict:
        """People who WORK within radius_m (100-1500) of the property, by sector (office, food service, retail,
        health care, education, arts/recreation) and earnings: the daytime population that drives walk-in demand."""
        r = max(100, min(int(radius_m), max_r))
        try:
            w = lodes.workers_within(state, lat, lon, r)
        except Exception as err:  # noqa: BLE001 - data gap, not a crash
            return {"summary": f"Daytime worker data unavailable here ({err}). Unknown, not zero.", "data": None, "source": LODES_SOURCE}
        band = _benchmark(ctx, "daytime_workers", w["total_jobs"], r)
        sec = w["by_sector"]
        return {
            "summary": f"{w['total_jobs']:,} jobs within {r} m (office {sec['office']:,}, food service {sec['food_service']:,}, retail {sec['retail']:,}, health care {sec['health_care']:,})" + (f" — {band}" if band else ""),
            "data": {**w, "benchmark": band},
            "source": f"{LODES_SOURCE} {w['year']} (jobs by workplace block)",
            "url": LODES_URL,
            "guidance": [
                "Jobs are counted at the workplace census block: a measured proxy for daytime population and lunch/after-work foot traffic, not pedestrian counts.",
                "Benchmarks are planning heuristics for this business type, not market data.",
            ],
        }

    @tool
    def get_residents(radius_m: int) -> dict:
        """Employed people who LIVE within radius_m (100-1500) of the property, with their earnings mix, plus tract
        demographics when available: the evening/weekend and neighborhood customer base."""
        r = max(100, min(int(radius_m), max_r))
        try:
            res = lodes.residents_within(state, lat, lon, r)
        except Exception as err:  # noqa: BLE001
            return {"summary": f"Resident data unavailable here ({err}). Unknown, not zero.", "data": None, "source": LODES_SOURCE}
        band = _benchmark(ctx, "employed_residents", res["employed_residents"], r)
        mix = res["earnings_mix_pct"]
        acs = (ctx.census or {}).get("acs")
        tract = f"; tract median household income ${acs['median_household_income']:,.0f}" if acs and acs.get("median_household_income") else ""
        return {
            "summary": f"{res['employed_residents']:,} employed residents within {r} m (earnings: {mix['low']}% ≤$1,250/mo, {mix['mid']}% mid, {mix['high']}% >$3,333/mo){tract}" + (f" — {band}" if band else ""),
            "data": {**res, "benchmark": band, "tract_acs": acs},
            "source": f"{LODES_SOURCE} {res['year']} (employed residents by home block)" + (" + Census ACS" if acs else ""),
            "url": LODES_URL,
            "guidance": [
                "Counts only EMPLOYED residents (not children, retirees or non-working adults); the full population is larger.",
                "Earnings mix indicates spending power for this business's price point.",
            ],
        }

    comp_rule = ((ctx.business.get("neighborhood") or {}).get("competitors") or {})
    kind_word, kind_values = detect_kind(ctx)
    kind_by = comp_rule.get("kind_by")

    @tool
    def find_direct_competitors(radius_m: int) -> dict:
        """Direct competitors only (same type of business) within radius_m (100-1500), plus same-kind competitors
        when the user named a kind (e.g. cuisine or shop type), chains vs independents and the nearest ones."""
        if not places_ok:
            return UNAVAILABLE
        r = max(100, min(int(radius_m), max_r))
        direct = [p for p in places if p["distance_m"] <= r and _matches(p, comp_rule.get("match", {}))]
        same_kind = []
        if kind_values:
            field_name = "cuisine" if kind_by == "cuisine" else None
            for p in direct:
                raw = (p.get(field_name) if field_name else (p.get("category") or "").partition("=")[2]) or ""
                if any(v in raw.lower().split(";") or v == raw.lower() for v in kind_values):
                    same_kind.append(p)
        chains = [p for p in direct if p.get("brand")]
        nearest = [
            {"name": p["name"] or "(unnamed)", "distance_m": p["distance_m"], "kind": p.get("cuisine") or (p.get("category") or "").partition("=")[2], "brand": p.get("brand")}
            for p in (same_kind or direct)[:6]
        ]
        kind_txt = f"; {len(same_kind)} serve/sell “{kind_word}”" if kind_word else ""
        return {
            "summary": f"{len(direct)} direct competitors within {r} m{kind_txt}; {len(chains)} chains, {len(direct) - len(chains)} independents"
            + (f"; nearest {direct[0]['distance_m']} m" if direct else ""),
            "data": {
                "radius_m": r, "direct_competitors": len(direct), "kind": kind_word, "same_kind_competitors": len(same_kind) if kind_word else None,
                "chains": len(chains), "independents": len(direct) - len(chains), "nearest_m": direct[0]["distance_m"] if direct else None, "nearest": nearest,
            },
            "source": "OpenStreetMap (Overpass)",
            "guidance": [
                "Direct = same business type; same-kind = the specific cuisine/shop the user named. Many direct competitors can mean a proven destination; many same-kind competitors means saturation.",
                "OpenStreetMap counts are a lower bound.",
            ],
        }

    @tool
    def get_walkable_reach(minutes: int = 10) -> dict:
        """What is actually reachable ON FOOT within `minutes` (5-15) by real walking routes, vs a straight-line
        circle: reveals highways, rail or water that cut off customers and transit."""
        if not places_ok:
            return UNAVAILABLE
        m = max(5, min(int(minutes), 15))
        circle_m = m * walking.WALK_M_PER_MIN
        wanted = {g for gs in roles.values() for g in gs} or set(groups_cfg)
        cands = [p for p in places if p["distance_m"] <= circle_m and p["group"] in wanted][: walking.MAX_DESTINATIONS]
        secs, routed = walking.walk_seconds((lat, lon), [(p["lat"], p["lon"]) for p in cands])
        reach = [p for p, s in zip(cands, secs) if s is not None and s <= m * 60]
        per_group = {}
        for g in sorted({p["group"] for p in cands}):
            per_group[g] = {"straight_line": sum(1 for p in cands if p["group"] == g), "walkable": sum(1 for p in reach if p["group"] == g)}
        transit = sorted((s for p, s in zip(cands, secs) if p["group"] == "transit" and s is not None))
        blocked = round(100 * (1 - len(reach) / len(cands))) if cands else None
        return {
            "summary": f"Within a {m}-min walk: {len(reach)} of {len(cands)} nearby places are actually reachable"
            + (f" ({blocked}% cut off by barriers or longer routes)" if blocked else "")
            + (f"; nearest transit {transit[0] / 60:.0f} min" if transit else "; no transit within reach")
            + ("" if routed else " [estimated: walking router unavailable]"),
            "data": {"minutes": m, "straight_line_radius_m": circle_m, "places_in_circle": len(cands), "walkable_places": len(reach), "blocked_pct": blocked, "by_group": per_group, "nearest_transit_min": round(transit[0] / 60, 1) if transit else None, "routed": routed},
            "source": "OSRM foot routing on OpenStreetMap (routing.openstreetmap.de)" if routed else "Straight-line estimate (router unavailable)",
            "guidance": ["A high blocked share means the straight-line catchment overstates real walk-in reach; judge access and demand on the walkable numbers."],
        }

    tools = [count_places, get_building_mix, get_access_options]
    if settings.census_api_key:
        tools.append(get_demographics)  # only useful with a key; otherwise it can only say "unavailable"
    extra = {"daytime_workers": get_daytime_workers, "residents": get_residents, "competitors": find_direct_competitors, "walk_access": get_walkable_reach}
    tools += [extra[s] for s in signals if s in extra]
    return tools


SIGNAL_TEXT = {
    "daytime_workers": "get_daytime_workers — people working nearby (daytime/lunch demand)",
    "residents": "get_residents — employed people living nearby + earnings mix (evening/weekend demand, spending power)",
    "competitors": "find_direct_competitors — same-type competitors, same cuisine/shop if named, chains vs independents",
    "walk_access": "get_walkable_reach — what is truly reachable on foot (barriers, transit by walking time)",
}


def task_prompt(ctx: RunContext, focus: str | None = None, signals: dict[str, str] | None = None) -> str:
    roles = ctx.business.get("place_roles", {})
    groups = place_groups()
    role_lines = "\n".join(f"- {role}: {', '.join(f'{g} ({groups[g]['label']})' for g in gs)}" for role, gs in roles.items() if gs)
    places_ok = any(src["name"].startswith("OpenStreetMap") and src["status"] == "used" for src in ctx.neighborhood.get("sources", []))
    available = ", ".join(f"{k} {v}" for k, v in list(ctx.neighborhood.get("place_groups", {}).items())[:10]) if places_ok else "UNAVAILABLE (OpenStreetMap request failed; counts unknown, not zero)"
    signals = signals if signals is not None else select_signals(ctx)[1]
    sig_lines = "\n".join(f"- {SIGNAL_TEXT[s]} ({why})" for s, why in signals.items() if s in SIGNAL_TEXT)
    kind_word, _ = detect_kind(ctx)
    base = (
        f"Investigate the neighborhood of the selected building for: \"{ctx.query}\".\n"
        f"Suggested catchment for a {ctx.business['label'].lower()}: {ctx.business['default_radius_m']} m — {ctx.business['radius_reason'].strip()} "
        f"(the user looked at {ctx.neighborhood.get('user_radius_m')} m). Choose radii per question: e.g. walking distance for access, the catchment for demand.\n"
        f"Place groups and what they mean for this business:\n{role_lines}\n"
        f"Places mapped within {ctx.neighborhood.get('user_radius_m')} m (overview): {available or 'none/unavailable'}.\n"
        + (f"Measured signals available for this business (use them for demand, competition and access):\n{sig_lines}\n" if sig_lines else "")
        + (f"The user named a kind: “{kind_word}” — judge competition on same-kind competitors, not all of them.\n" if kind_word else "")
        + "Investigate demand, competition, access and area fit; note where data gaps limit conclusions. "
        "Call independent tools together in one turn."
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
    calls += [("get_building_mix", {"radius_m": radius}), ("get_access_options", {"radius_m": 400})]
    signal_calls = {
        "daytime_workers": ("get_daytime_workers", {"radius_m": radius}),
        "residents": ("get_residents", {"radius_m": radius}),
        "competitors": ("find_direct_competitors", {"radius_m": radius}),
        "walk_access": ("get_walkable_reach", {"minutes": 10}),
    }
    calls += [signal_calls[name] for name in select_signals(ctx)[0] if name in signal_calls]
    if settings.census_api_key:
        calls.append(("get_demographics", {}))
    return calls


async def run(ctx: RunContext, budget_limit: int = 7, focus: str | None = None, metric_ids: list[str] | None = None) -> AgentReport:
    lodes.warm(ctx.property.get("state"))  # load Census jobs/residents in the background while the agent thinks
    names, why = select_signals(ctx)
    if names:
        ctx.emit("neighborhood", "plan", "Signals: " + "; ".join(f"{s.replace('_', ' ')} ({w})" for s, w in why.items()), {"signals": names})
    budget = ToolBudget(budget_limit + (1 if len(names) > 2 else 0), ctx.shared.setdefault("seen:neighborhood", {}))
    tools = build_tools(ctx, budget, names)
    if ctx.mode == "quick" and not focus:
        budget.limit = 20  # room for the pre-gathered calls; reset to used + 2 after prefetch
        return await run_agent(ctx, "neighborhood", ROLE, task_prompt(ctx, signals=why), tools, budget, metric_ids=metric_ids, prefetch_calls=quick_prefetch(ctx), max_model_calls=3)
    return await run_agent(ctx, "neighborhood", ROLE, task_prompt(ctx, focus, why), tools, budget, metric_ids=metric_ids)
