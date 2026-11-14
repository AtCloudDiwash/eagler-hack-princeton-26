"""Deterministic, config-driven cost engine (backend/config/costs.yaml). Ranges only, never ML.

    hard costs        = sum(line items)             each: band x qty, per_sqft: band x sq ft
    general cond.     = hard x general_conditions_pct
    contingency       = (hard + general cond.) x contingency_pct
    permits           = flat band (always: any tenant build-out needs a permit)
    fit-out (gross)   = hard + general cond. + contingency + permits
    TI allowance      = ti_allowance_per_sqft x size
    net fit-out       = max(0, fit-out - TI)
    build-out months  = business base months + adds_months of each line item
    cost to open      = net fit-out + rent x build-out months     (AnalysisResult.total_cost_estimate)
    first-year cost   = cost to open + horizon_months x rent       (ranking basis)

Min and max are computed independently (min uses every lower bound, max every upper bound).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import business_types, cost_config
from ..models import CostLineItem, CostRange, Property
from .evaluators import CostNeed


class UnknownCostItem(KeyError):
    pass


@dataclass
class CostEstimate:
    line_items: list[CostLineItem]
    breakdown: dict[str, CostRange]
    hard_costs: CostRange
    fit_out: CostRange
    ti_allowance: float
    net_fit_out: CostRange
    buildout_months: CostRange
    cost_to_open: CostRange
    first_year: CostRange
    horizon_months: int
    assumptions: list[str] = field(default_factory=list)


def _range(lo: float, hi: float) -> CostRange:
    return CostRange(min=round(lo), max=round(hi))


def merge_needs(needs: list[CostNeed]) -> list[CostNeed]:
    """One line per cost item: keep the largest quantity, join distinct reasons."""
    merged: dict[str, CostNeed] = {}
    for need in needs:
        if need.item in merged:
            current = merged[need.item]
            current.qty = max(current.qty, need.qty)
            if need.reason not in current.reason:
                current.reason = f"{current.reason}; {need.reason}"
        else:
            merged[need.item] = CostNeed(need.item, need.qty, need.reason)
    return list(merged.values())


def price_item(item_id: str, qty: float, reason: str = "") -> CostLineItem:
    items = cost_config()["items"]
    if item_id not in items:
        raise UnknownCostItem(f"Cost item '{item_id}' is not defined in config/costs.yaml")
    cfg = items[item_id]
    return CostLineItem(
        item=item_id,
        label=cfg.get("label", item_id),
        qty=qty,
        min=round(cfg["min"] * qty),
        max=round(cfg["max"] * qty),
        reason=reason,
    )


def estimate(needs: list[CostNeed], prop: Property, business: dict) -> CostEstimate:
    cfg = cost_config()
    soft = cfg.get("soft_costs", {})
    horizon = int(cfg.get("ranking", {}).get("horizon_months", 12))

    hard_items = [price_item(n.item, n.qty, n.reason) for n in merge_needs(needs)]
    hard_lo = sum(i.min for i in hard_items)
    hard_hi = sum(i.max for i in hard_items)

    soft_items: list[CostLineItem] = []
    gc = soft.get("general_conditions_pct", {"min": 0, "max": 0})
    gc_lo, gc_hi = hard_lo * gc["min"], hard_hi * gc["max"]
    if hard_items:
        soft_items.append(
            CostLineItem(
                item="general_conditions_pct", label=gc.get("label", "General conditions"), qty=1,
                min=round(gc_lo), max=round(gc_hi),
                reason=f"{gc['min']:.0%}-{gc['max']:.0%} of construction costs",
            )
        )
        cont = soft.get("contingency_pct", {"min": 0, "max": 0})
        soft_items.append(
            CostLineItem(
                item="contingency_pct", label=cont.get("label", "Contingency"), qty=1,
                min=round((hard_lo + gc_lo) * cont["min"]), max=round((hard_hi + gc_hi) * cont["max"]),
                reason=f"{cont['min']:.0%}-{cont['max']:.0%} of construction + general conditions",
            )
        )
    permits = soft.get("permits_fees")
    if permits:
        soft_items.append(
            CostLineItem(
                item="permits_fees", label=permits.get("label", "Permits and fees"), qty=1,
                min=permits["min"], max=permits["max"], reason="Building / health permits for tenant improvements",
            )
        )

    line_items = hard_items + soft_items
    fit_lo = sum(i.min for i in line_items)
    fit_hi = sum(i.max for i in line_items)
    ti = round((prop.ti_allowance_per_sqft or 0) * prop.size_sqft)
    net_lo, net_hi = max(0, fit_lo - ti), max(0, fit_hi - ti)

    base = business.get("buildout_months", {"min": 1, "max": 2})
    months_lo, months_hi = float(base["min"]), float(base["max"])
    items_cfg = cfg["items"]
    for item in hard_items:
        adds = items_cfg[item.item].get("adds_months") or {}
        months_lo += adds.get("min", 0)
        months_hi += adds.get("max", 0)

    open_lo = net_lo + prop.rent * months_lo
    open_hi = net_hi + prop.rent * months_hi
    assumptions = [
        f"Build-out of {months_lo:g}-{months_hi:g} months with rent paid before opening.",
        f"First-year cost = cost to open + {horizon} months of rent.",
    ]
    if ti:
        assumptions.append(f"Landlord TI allowance of ${prop.ti_allowance_per_sqft:g}/sq ft (${ti:,}) offsets fit-out.")

    return CostEstimate(
        line_items=line_items,
        breakdown={i.item: _range(i.min, i.max) for i in line_items},
        hard_costs=_range(hard_lo, hard_hi),
        fit_out=_range(fit_lo, fit_hi),
        ti_allowance=float(ti),
        net_fit_out=_range(net_lo, net_hi),
        buildout_months=CostRange(min=months_lo, max=months_hi),
        cost_to_open=_range(open_lo, open_hi),
        first_year=_range(open_lo + horizon * prop.rent, open_hi + horizon * prop.rent),
        horizon_months=horizon,
        assumptions=assumptions,
    )


# --------------------------------------------------------------------------------------------
# Convenience helpers (prompts/02-agent-workflow.md)
# --------------------------------------------------------------------------------------------


def estimate_cost(missing_items: list[str], profile=None, size_sqft: int | None = None) -> tuple[float, float]:
    """Sum hard-cost bands for item ids (qty 1; per_sqft items use size_sqft or the business's typical size).

    `profile` may be a BusinessProfile, Requirements or a business type string; it is only used to
    size per-sq-ft items. Returns (min, max) for the listed items, before soft costs.
    """
    items = cost_config()["items"]
    if size_sqft is None:
        business_type = getattr(profile, "type", None) or getattr(profile, "business_type", None) or profile
        biz = business_types().get(business_type, {}) if isinstance(business_type, str) else {}
        size_sqft = int(biz.get("default_capacity", 0) * biz.get("sqft_per_capacity_unit", 0)) or 2000
    lo = hi = 0.0
    for item_id in missing_items:
        qty = size_sqft if items.get(item_id, {}).get("unit") == "per_sqft" else 1
        line = price_item(item_id, qty)
        lo += line.min
        hi += line.max
    return lo, hi


def estimate_kitchen_cost(has_kitchen: bool) -> tuple[float, float]:
    return (0.0, 0.0) if has_kitchen else estimate_cost(["kitchen_install"])
