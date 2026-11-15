"""What this building offers THIS user: the panel tiles shown when a building is selected for a request.

Instead of whole-building figures (the tower's rentable area, its footprint), the tiles answer the user's question:
which space we suggest for their request, how it fits their size, what it would cost them (deterministic cost
engine), whether that fits their budget, and the deal-breaker checks for their use (street level, permitted use,
parking minimum, prior build-out). Same nine tiles, same order, for every building; nothing here calls an LLM or
the network. Each tile: {"id", "label", "value", "hint", "source", "icon", "status", "missing"} where status is
good | warn | bad | unknown.
"""
from __future__ import annotations

from typing import Any

from config import business
from schemas import Intent
from services import building_facts, costar, rules
from services import costs as cost_engine
from services import program as space_program

NET_SERVICE = {"TripleNet", "Net", "DoubleNet"}  # net rents the cost engine can use (it adds NNN itself)
PRIOR_USE_FOR = {"restaurant": {"restaurant"}, "medical_office": {"dental", "medical"}}


def _k(v: float) -> str:
    return f"${v / 1000:,.0f}k" if v >= 10_000 else f"${v / 1000:,.1f}k" if v >= 1000 else f"${v:,.0f}"


def _jurisdiction(address: str | None) -> tuple[str, dict]:
    parts = [p.strip() for p in (address or "").split(",")]
    city, state = (parts[-2], parts[-1].split()[0] if parts[-1] else "") if len(parts) >= 3 else (None, None)
    return rules.jurisdiction_for(city, state)


def _tile(id_: str, label: str, icon: str, value: str | None, hint: str, source: str, status: str = "unknown", missing: str = "Unknown", sub: str | None = None) -> dict:
    """`value` is the short headline (a number or one word, fits the card); `sub` is a small line of context."""
    if value:
        return {"id": id_, "label": label, "value": value, "sub": sub, "hint": hint, "source": source, "icon": icon, "status": status, "missing": False}
    return {"id": id_, "label": label, "value": "Unknown" if len(missing) > 11 else missing, "sub": missing.lower() if len(missing) > 11 else sub, "hint": hint, "source": "none", "icon": icon, "status": "unknown", "missing": True}


def tiles(prop: dict, feature: dict | None, intent: Intent) -> list[dict]:
    cfg = business(intent.business_type)
    prog = space_program.build(intent)
    target, lo, hi = prog["size"]["target_sqft"], prog["size"]["min_sqft"], prog["size"]["max_sqft"]
    ground_rule = prog["building"]["ground_floor"]
    rec = costar.match(prop["lat"], prop["lon"], prop.get("footprint")) if prop.get("lat") is not None else None
    fields = costar.candidate_fields(rec, lo, hi, target, ground_rule == "required") if rec else {}
    best = fields.get("best_space") or {}
    known = building_facts.facts(prop, feature)["facts"]
    use = cfg["zoning_use"]
    out: list[dict] = []

    # 1. the space we suggest for this request
    if best.get("sqft"):
        name = str(best.get("suite") or "")
        suite = f"Suite {name}" if name and len(name) <= 8 else "Listed suite"  # CoStar suite names can be long ("Open-Plan for +15")
        out.append(_tile("space", "Suggested space", "space", f"{best['sqft']:,.0f} sq ft", sub=suite, hint=
                         (f"Suite {name}: " if name and suite == "Listed suite" else "") + f"the CoStar listing here closest to your ~{target:,} sq ft ({best.get('use') or 'use not stated'}" + (f", available {str(best['available_on'])[:7]}" if best.get("available_on") else "") + ").",
                         source="CoStar listing", status="good"))
    elif fields.get("space_count"):
        out.append(_tile("space", "Suggested space", "space", "None fit", sub=f"{fields['space_count']} listed, none {lo:,}–{hi:,} sq ft", hint=f"CoStar lists {fields['space_count']} space(s) here ({fields.get('available_sqft') or 0:,.0f} sq ft), none in your size range; ask about dividing or combining.", source="CoStar listings", status="warn"))
    else:
        out.append(_tile("space", "Suggested space", "space", None, "No space at this building is listed for lease in the CoStar snapshot; contact the owner about availability.", "CoStar", missing="Not listed", sub="no suite for lease"))

    # 2. size vs need
    sqft = best.get("sqft")
    fp = known.get("footprint_sqft", {}).get("value") or prop.get("area_sqft")
    if sqft:
        ratio = sqft / target
        out.append(_tile("size", "Size vs your need", "floors", f"{ratio:.0%}", sub=f"of ~{target:,} sq ft", hint=f"{sqft:,.0f} sq ft listed vs your {lo:,}–{hi:,} sq ft range.", source="CoStar listing", status="good" if lo <= sqft <= hi else "warn"))
    elif fp:
        ratio = fp / target
        out.append(_tile("size", "Size vs your need", "floors", f"{ratio:.1f}×", sub="one floor vs your need (est.)", hint=f"One floor (aerial footprint {fp:,.0f} sq ft) vs your ~{target:,} sq ft; you would lease part of the building (unverified: no listing).",
                         source="Vexcel", status="warn" if ratio >= 0.85 else "bad"))
    else:
        out.append(_tile("size", "Size vs your need", "floors", None, "No listing or footprint to compare with your size.", "none", missing="Unknown", sub="no size data"))

    # 3-5. what it would cost this user (deterministic cost engine)
    jkey, jur = _jurisdiction(prop.get("address"))
    prior = known.get("second_generation_use")
    second_gen = bool(prior and prior["value"] in PRIOR_USE_FOR.get(use, set()) and prior.get("confidence") in ("high", "medium"))
    rate = best.get("rent_per_sqft_yr")
    rent = {"per_sqft_low": rate, "per_sqft_high": rate, "source": "CoStar listing"} if rate and best.get("service") in NET_SERVICE else None
    est = cost_engine.estimate(intent.business_type, sqft or target, jkey, [], second_gen, rent)
    basis = f"{(sqft or target):,.0f} sq ft for a {cfg['label'].lower()}, " + ("the listing's net asking rent" if rent else "local planning rent band") + (", second-generation space" if second_gen else "") + "; base fit-out only (the analysis adds items the evidence triggers)."
    m, u = est["monthly_occupancy"], est["upfront"]
    out.append(_tile("monthly", "Est. monthly", "rent", f"{_k(m['low'])}–{_k(m['high']).lstrip('$')}", sub="per month, all-in", hint=f"Rent + NNN + fit-out amortized over the lease. {basis}", source="Cost engine"))
    out.append(_tile("upfront", "Est. upfront", "cam", f"{_k(u['low'])}–{_k(u['high']).lstrip('$')}", sub="fit-out + deposit", hint=f"Fit-out, permits, contingency and deposit. {basis}", source="Cost engine"))
    check = cost_engine.budget_check(est, intent.budget.model_dump() if intent.budget else None, intent.business_type)
    label = {"within": "Within", "partly": "Partly", "over": "Over"}[check["status"]]
    per = "/mo" if check["period"] == "monthly" else "/yr" if check["period"] == "annual" else ""
    out.append(_tile("budget", "Your budget" if intent.budget else "Typical budget", "rent", label, sub=(f"of your {_k(check['amount'])}{per}" if intent.budget else f"vs ~{_k(check['amount'])}") + ("" if intent.budget else " typical"),
                     hint=check["note"], source="Cost engine", status={"within": "good", "partly": "warn", "over": "bad"}[check["status"]]))

    # 6. street level, judged against what this use needs
    g = best.get("ground_floor") if best else None
    if g is None and known.get("stories", {}).get("source") == "CoStar" and known["stories"]["value"] == 1:
        g = True
    need = {"required": "this use needs street level", "preferred": "street level preferred for this use", "any": "any floor works for this use"}[ground_rule]
    if g is None:
        out.append(_tile("street", "Street level", "building", None, f"Not recorded for this space; {need}.", "none", missing="Unknown", sub="floor not recorded"))
    else:
        floor = building_facts._floor_label(best["floor"]) if best.get("floor") else "single story"
        out.append(_tile("street", "Street level", "building", "Yes" if g else "No", sub=floor, hint=f"{need.capitalize()} (CoStar listing).", source="CoStar listing", status=
                         "good" if g else ("bad" if ground_rule == "required" else "warn" if ground_rule == "preferred" else "good")))

    # 7. permitted use (verified rule set)
    pu = rules.permitted_use(jur, intent.business_type)
    out.append(_tile("permitted", "Permitted use", "year", {"pass": "Allowed", "risk": "Conditional", "fail": "Not allowed", "unknown": None}[pu["status"]], sub=jur["name"] if pu["status"] != "unknown" else "verify with the city",
                     hint=pu["detail"][:220] + (f" ({pu['citation']})" if pu.get("citation") else ""), source=jur["name"], status={"pass": "good", "risk": "warn", "fail": "bad"}.get(pu["status"], "unknown"), missing="Unknown"))

    # 8. parking minimum for this use and size vs what's recorded
    spaces = known.get("parking_spaces") if known.get("parking_spaces", {}).get("source") == "CoStar" else None
    pk = rules.parking_requirement(jur, intent.business_type, sqft or target, prop["lat"], prop["lon"], (feature or {}).get("properties", {}).get("hardscapes.area"), spaces["value"] if spaces else None)
    ev = pk.get("evidence") or {}
    if pk["status"] == "unknown":
        out.append(_tile("parking", "Parking minimum", "parking", None, pk["detail"], "none", missing="Unknown", sub="rule not verified"))
    elif ev.get("exempt_area") or ev.get("required_spaces") == 0:
        out.append(_tile("parking", "Parking minimum", "parking", "None", sub="required here", hint=pk["detail"], source=jur["name"], status="good"))
    else:
        est = ev.get("estimated_onsite_spaces") or 0
        have = f"{ev['recorded_spaces']:,} recorded" if ev.get("recorded_spaces") else (f"~{est} on site (est.)" if est else "none recorded")
        out.append(_tile("parking", "Parking minimum", "parking", f"{ev['required_spaces']} needed", sub=have, hint=pk["detail"], source=jur["name"], status="good" if pk["status"] == "pass" else "warn"))

    # 9. prior build-out (a second-generation space saves much of the fit-out)
    if prior:
        same = prior["value"] in PRIOR_USE_FOR.get(use, set())
        out.append(_tile("prior", "Prior build-out", "kitchen", prior["value"].title(), sub="2nd-gen, same use" if same else "different use", hint=
                         f"{prior.get('note') or 'Recorded prior build-out'} ({prior['confidence']} confidence)." + (" Same use as yours: lower fit-out." if same else ""), source="CoStar", status="good" if same else "unknown"))
    else:
        out.append(_tile("prior", "Prior build-out", "kitchen", None, f"No prior {cfg['label'].lower()} build-out recorded; assume a full fit-out.", "CoStar", missing="None", sub="full fit-out assumed"))
    return out


def intent_from_params(business_type: str | None, sqft: int | None, budget_amount: float | None, budget_period: str | None) -> Intent | None:
    if not business_type:
        return None
    budget: Any = {"amount": budget_amount, "period": budget_period} if budget_amount and budget_period in ("monthly", "upfront", "annual") else None
    return Intent(business_type=business_type, sqft=sqft or None, budget=budget)
