"""Deterministic cost engine over config/costs.yaml. Same inputs -> same ranges (reproducible).

The Cost Agent decides WHICH adders apply (and cites the evidence that triggered them); every number
is computed here from documented bands.
"""
from __future__ import annotations

from config import business, costs_config


def _band(table: dict, key: str) -> dict:
    return table.get(key) or table["_default"]


def rent_band(jurisdiction_key: str, business_type: str) -> dict:
    cfg = costs_config()["rent_bands"]
    use = business(business_type)["zoning_use"]
    table = cfg.get(jurisdiction_key) or cfg["_default"]
    band = table.get(use) or cfg["_default"][use]
    return {"per_sqft_low": band["low"], "per_sqft_high": band["high"], "source": table.get("source", cfg["_default"]["source"])}


def estimate(business_type: str, sqft: float, jurisdiction_key: str, adders: list[dict], second_generation: bool = False) -> dict:
    """adders: [{id, quantity, reason, evidence_ids}]. Returns a Costs dict (see api-types.ts)."""
    cfg = costs_config()
    use = business(business_type)["zoning_use"]
    sqft = max(float(sqft), 300.0)
    assumptions = [cfg["disclaimer"].strip()]

    base = cfg["base_fitout_per_sqft"][use]
    base_low, base_high = base["low"], base["high"]
    if second_generation:
        base_high = base_low + (base_high - base_low) * 0.4
        assumptions.append("Second-generation space assumed (prior same use): base fit-out at the low end of the band.")
    lines = [{
        "id": "base_fitout",
        "label": f"Base tenant fit-out ({sqft:,.0f} sq ft × ${base_low:.0f}–{base_high:.0f}/sq ft)",
        "low": round(sqft * base_low),
        "high": round(sqft * base_high),
        "reason": "Standard build-out band for this use (planning assumption).",
        "evidence_ids": [],
    }]
    rejected = []
    for a in adders:
        spec = cfg["adders"].get(a.get("id", ""))
        if not spec or use not in spec["applies_to"]:
            rejected.append(a.get("id"))
            continue
        qty = max(1, int(a.get("quantity") or 1))
        if spec["unit"] == "per_sqft":
            low, high, label = sqft * spec["low"], sqft * spec["high"], f"{spec['label']} ({sqft:,.0f} sq ft)"
        else:
            low, high, label = qty * spec["low"], qty * spec["high"], spec["label"] + (f" × {qty}" if qty > 1 else "")
        lines.append({"id": a["id"], "label": label, "low": round(low), "high": round(high), "reason": a.get("reason") or "", "evidence_ids": a.get("evidence_ids") or []})

    subtotal_low = sum(l["low"] for l in lines)
    subtotal_high = sum(l["high"] for l in lines)
    soft = cfg["soft_costs"]
    lines.append({"id": "permits_fees", "label": "Permits & fees", "low": soft["permits_fees"]["low"], "high": soft["permits_fees"]["high"], "reason": "Typical permit/plan-review fees.", "evidence_ids": []})
    lines.append({
        "id": "contingency",
        "label": f"Contingency ({soft['contingency_pct']['low']:.0%}–{soft['contingency_pct']['high']:.0%})",
        "low": round(subtotal_low * soft["contingency_pct"]["low"]),
        "high": round(subtotal_high * soft["contingency_pct"]["high"]),
        "reason": "Unknowns in an unseen interior.",
        "evidence_ids": [],
    })
    fit_low = sum(l["low"] for l in lines)
    fit_high = sum(l["high"] for l in lines)

    rent = rent_band(jurisdiction_key, business_type)
    nnn = cfg["nnn_per_sqft_year"]
    lease = cfg["lease"]
    annual_low, annual_high = sqft * rent["per_sqft_low"], sqft * rent["per_sqft_high"]
    monthly_low = (annual_low + sqft * nnn["low"]) / 12 + fit_low / (lease["amortize_fitout_years"] * 12)
    monthly_high = (annual_high + sqft * nnn["high"]) / 12 + fit_high / (lease["amortize_fitout_years"] * 12)
    deposit_low, deposit_high = annual_low / 12 * lease["deposit_months"], annual_high / 12 * lease["deposit_months"]
    assumptions += [
        f"Rent ${rent['per_sqft_low']}–{rent['per_sqft_high']}/sq ft/yr NNN: {rent['source']}.",
        f"NNN (taxes, insurance, CAM) ${nnn['low']}–{nnn['high']}/sq ft/yr.",
        f"Monthly view amortizes fit-out over {lease['amortize_fitout_years']} years; upfront includes a {lease['deposit_months']}-month deposit.",
    ]
    if rejected:
        assumptions.append(f"Ignored cost items not applicable to this use: {', '.join(str(r) for r in rejected)}.")
    typical = cfg["typical_upfront_per_sqft"][use]
    return {
        "currency": "USD",
        "sqft_used": round(sqft),
        "sqft_basis": "",
        "rent": {"low_annual": round(annual_low), "high_annual": round(annual_high), "per_sqft_low": rent["per_sqft_low"], "per_sqft_high": rent["per_sqft_high"], "source": rent["source"]},
        "fitout": {"low": round(fit_low), "high": round(fit_high), "line_items": lines},
        "monthly_occupancy": {"low": round(monthly_low), "high": round(monthly_high)},
        "upfront": {"low": round(fit_low + deposit_low), "high": round(fit_high + deposit_high)},
        "assumptions": assumptions,
        "_benchmark": {"upfront_per_sqft_mid": round((fit_low + fit_high) / 2 / sqft), "typical_good": typical["good"], "typical_high": typical["high"]},
    }


def budget_check(costs: dict, budget: dict | None, business_type: str) -> dict:
    """Compare the estimate with the user's budget, or (if none was given) with a typical budget for this use
    and size. Pure Python: same inputs, same answer."""
    sqft = costs["sqft_used"] or 1
    if budget:
        period, amount = budget["period"], float(budget["amount"])
        if period == "monthly":
            low, high = costs["monthly_occupancy"]["low"], costs["monthly_occupancy"]["high"]
        elif period == "annual":
            low, high = costs["monthly_occupancy"]["low"] * 12, costs["monthly_occupancy"]["high"] * 12
        else:
            low, high = costs["upfront"]["low"], costs["upfront"]["high"]
        source, label = "user", {"monthly": "monthly", "annual": "annual", "upfront": "upfront"}[period]
        note = f"Your {label} budget of ${amount:,.0f} vs an estimated ${low:,.0f}–${high:,.0f}."
    else:
        use = business(business_type)["zoning_use"]
        typical = costs_config()["typical_upfront_per_sqft"][use]
        period, amount = "upfront", round(sqft * typical["good"], -3)
        low, high = costs["upfront"]["low"], costs["upfront"]["high"]
        source = "typical"
        note = (
            f"You didn't specify a budget, so this compares against a typical upfront budget for a "
            f"{business(business_type)['label'].lower()} of about {sqft:,.0f} sq ft (≈${amount:,.0f}, based on your choices)."
        )
    status = "within" if high <= amount else "partly" if low <= amount else "over"
    return {"source": source, "period": period, "amount": amount, "compare_low": low, "compare_high": high, "status": status, "note": note}


def user_budgets(intent: dict) -> list[dict]:
    """Every budget the user stated (one per period), falling back to the single primary budget."""
    return list(intent.get("budgets") or ([intent["budget"]] if intent.get("budget") else []))


def budget_checks(costs: dict, intent: dict, business_type: str) -> list[dict]:
    """One check per stated budget; with none stated, a single check against a typical budget."""
    budgets = user_budgets(intent)
    return [budget_check(costs, b, business_type) for b in budgets] if budgets else [budget_check(costs, None, business_type)]


def worst(checks: list[dict]) -> dict:
    order = {"over": 0, "partly": 1, "within": 2}
    return min(checks, key=lambda c: order[c["status"]])


def budget_status(check: dict) -> str:
    return {"within": "strong", "partly": "adequate", "over": "weak"}[check["status"]]


def cost_status(costs: dict) -> str:
    """Python rule for the occupancy_cost metric: compare upfront $/sq ft with typical budgets."""
    b = costs["_benchmark"]
    mid = b["upfront_per_sqft_mid"]
    if mid <= b["typical_good"]:
        return "strong"
    if mid <= (b["typical_good"] + b["typical_high"]) / 2:
        return "adequate"
    return "weak"


def conversion_risk_status(costs: dict) -> str:
    """Share of the fit-out budget driven by assumption-based (uncited) adders + contingency."""
    lines = costs["fitout"]["line_items"]
    total_high = costs["fitout"]["high"] or 1
    uncertain = sum(l["high"] for l in lines if l["id"] == "contingency" or (l["id"] not in {"base_fitout", "permits_fees"} and not l["evidence_ids"]))
    share = uncertain / total_high
    return "strong" if share < 0.15 else "adequate" if share < 0.3 else "weak"
