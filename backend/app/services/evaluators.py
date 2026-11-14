"""Evaluator registry: maps `evaluator` names in criteria.yaml to Python functions.

Each evaluator receives an `EvalContext` (requirements, property, observed facts, the criterion's
thresholds, jurisdiction rules) and returns an `EvalOutcome`:

    status              PASS | RISK | UNKNOWN
    notes               one plain-English sentence or two for the report
    evidence            facts behind the finding (observed and derived)
    cost_items          cost items (ids from config/costs.yaml) the fix needs, with qty + reason
    questions           questions to ask the landlord
    definitive_failure  True only when a RISK is a known failure (not a data gap). Combined with a
                        criterion's `hard_block`, this disqualifies the property.

The compliance engine checks `required_inputs` before calling an evaluator, so evaluators may
assume those inputs are present. When inputs are missing and the criterion's policy is
`assume_cost`, the engine calls the evaluator's registered `fallback` to price the fix anyway.

To add a check: write a function, decorate it with @evaluator("name"), reference "name" in
criteria.yaml. Nothing else changes.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..models import Criterion, Evidence, Property, Requirements, Status


@dataclass
class CostNeed:
    item: str  # id from config/costs.yaml `items`
    qty: float
    reason: str


@dataclass
class EvalContext:
    requirements: Requirements
    property: Property
    observations: dict[str, Evidence]
    criterion: Criterion
    jurisdiction: dict[str, Any]
    business: dict[str, Any]
    inputs: dict[str, Any] = field(default_factory=dict)

    @property
    def thresholds(self) -> dict[str, Any]:
        return self.criterion.thresholds

    def value(self, key: str) -> Any:
        """Input value by name (observed fact, requirement or listing field), or None."""
        return self.inputs.get(key)

    def evidence(self, *keys: str) -> list[Evidence]:
        return [self.observations[k] for k in keys if k in self.observations]

    def derived(self, key: str, value: Any, note: str, source: str = "requirements") -> Evidence:
        return Evidence(key=key, value=value, source=source, note=note)


@dataclass
class EvalOutcome:
    status: Status
    notes: str
    evidence: list[Evidence] = field(default_factory=list)
    cost_items: list[CostNeed] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    definitive_failure: bool = False
    source: str | None = None  # overrides the criterion's `source` when set (e.g. jurisdiction citation)


EvaluatorFn = Callable[[EvalContext], EvalOutcome]
FallbackFn = Callable[[EvalContext], list[CostNeed]]


@dataclass
class EvaluatorSpec:
    name: str
    func: EvaluatorFn
    fallback: FallbackFn | None = None


_REGISTRY: dict[str, EvaluatorSpec] = {}


def evaluator(name: str, fallback: FallbackFn | None = None) -> Callable[[EvaluatorFn], EvaluatorFn]:
    """Register `func` under `name`. `fallback` prices the fix when required inputs are missing."""

    def decorate(func: EvaluatorFn) -> EvaluatorFn:
        _REGISTRY[name] = EvaluatorSpec(name=name, func=func, fallback=fallback)
        return func

    return decorate


def get_evaluator(name: str) -> EvaluatorSpec | None:
    return _REGISTRY.get(name)


def registered_evaluators() -> list[str]:
    return sorted(_REGISTRY)


def _plural(n: float, word: str) -> str:
    return f"{n:g} {word}{'' if n == 1 else 's'}"


# --------------------------------------------------------------------------------------------
# Zoning
# --------------------------------------------------------------------------------------------


def base_zoning_district(code: str, known: set[str]) -> str:
    """'CS-MU' -> 'CS', 'LR-V' -> 'LR', 'CS-1-MU-CO' -> 'CS-1'. Keeps the longest known prefix."""
    parts = code.strip().upper().split("-")
    for end in range(len(parts), 0, -1):
        candidate = "-".join(parts[:end])
        if candidate in known:
            return candidate
    return parts[0]


@evaluator("zoning_checker")
def zoning_checker(ctx: EvalContext) -> EvalOutcome:
    code = str(ctx.value("zoning_code")).strip().upper()
    use = ctx.business.get("zoning_use", ctx.requirements.business_type)
    table = (ctx.jurisdiction.get("zoning") or {}).get(use)
    source = ctx.jurisdiction.get("zoning_source") or ctx.criterion.source
    evidence = ctx.evidence("zoning_code")
    if not table:
        return EvalOutcome(
            "UNKNOWN",
            f"No zoning use table loaded for {ctx.jurisdiction.get('name', 'this city')}; "
            f"verify that '{code}' allows a {ctx.requirements.business_label.lower()} with the city.",
            evidence,
            questions=[f"Can you confirm the zoning ({code}) permits a {ctx.requirements.business_label.lower()} use?"],
            source=source,
        )
    lists = {k: {d.upper() for d in table.get(k, [])} for k in ("permitted", "conditional", "prohibited")}
    district = base_zoning_district(code, set().union(*lists.values()))
    suffix = f" (base district {district})" if district != code else ""
    if district in lists["permitted"]:
        status, verdict, definitive = "PASS", "permitted", False
        notes = f"Zoning {code}{suffix} permits {use.replace('_', ' ')} use."
    elif district in lists["conditional"]:
        status, verdict, definitive = "RISK", "conditional", False
        notes = (
            f"Zoning {code}{suffix} allows {use.replace('_', ' ')} only with a conditional use permit "
            "(extra approval time and a public hearing)."
        )
    elif district in lists["prohibited"]:
        status, verdict, definitive = "RISK", "prohibited", True
        notes = f"Zoning {code}{suffix} does not permit {use.replace('_', ' ')} use; a rezoning would be required."
    else:
        return EvalOutcome(
            "UNKNOWN",
            f"District '{district}' is not in the simplified {ctx.jurisdiction.get('name')} use table; verify with the city.",
            evidence,
            questions=[f"Can you confirm the zoning ({code}) permits a {ctx.requirements.business_label.lower()} use?"],
            source=source,
        )
    evidence = evidence + [
        ctx.derived("zoning_rule", f"{district}: {verdict}", f"{ctx.jurisdiction.get('name')} use table", "jurisdiction")
    ]
    questions = []
    if verdict == "conditional":
        questions.append("Has a conditional use permit for this use been granted here before, and will you support the application?")
    return EvalOutcome(status, notes, evidence, questions=questions, definitive_failure=definitive, source=source)


# --------------------------------------------------------------------------------------------
# Parking / accessibility
# --------------------------------------------------------------------------------------------


@evaluator("parking_checker")
def parking_checker(ctx: EvalContext) -> EvalOutcome:
    visible = float(ctx.value("visible_parking_count"))
    required = float(ctx.value("business_required_parking"))
    min_ratio = float(ctx.thresholds.get("min_ratio", 1.0))
    basis = "you stated" if ctx.requirements.parking_source == "user" else "the business guideline"
    evidence = ctx.evidence("visible_parking_count") + [
        ctx.derived("business_required_parking", int(required), f"Spaces needed ({basis})")
    ]
    note = ctx.jurisdiction.get("parking_note", "")
    source = f"{ctx.criterion.source}. {note}".strip()
    if required <= 0 or visible / required >= min_ratio:
        return EvalOutcome("PASS", f"{visible:g} spaces visible vs {required:g} needed.", evidence, source=source)
    return EvalOutcome(
        "RISK",
        f"Only {visible:g} spaces visible vs {required:g} needed ({basis}). {note}".strip(),
        evidence,
        questions=[f"How many of the {visible:g} visible parking spaces are reserved for this unit, and is overflow parking available nearby?"],
        source=source,
    )


@evaluator("ada_checker")
def ada_checker(ctx: EvalContext) -> EvalOutcome:
    width = float(ctx.value("door_width_inches"))
    min_width = float(ctx.thresholds.get("min_width", 32))
    step_free = ctx.value("step_free_entrance")
    evidence = ctx.evidence("door_width_inches", "step_free_entrance")
    problems, costs, questions = [], [], []
    if width < min_width:
        problems.append(f"entrance door is {width:g} in. wide (needs {min_width:g} in. clear)")
        costs.append(CostNeed("door_widening", 1, f"Door {width:g} in. < {min_width:g} in. ADA clear width"))
    if step_free is False:
        problems.append("entrance has steps")
        costs.append(CostNeed("entrance_ramp", 1, "No step-free entrance"))
    elif step_free is None:
        questions.append("Is the main entrance step-free (no steps or thresholds over 1/2 in.)?")
    if problems:
        return EvalOutcome(
            "RISK",
            "ADA barrier: " + "; ".join(problems) + ".",
            evidence,
            costs,
            questions + ["Will the landlord cover ADA entrance upgrades as part of base building work?"],
        )
    tail = " and step-free entry" if step_free else ""
    return EvalOutcome("PASS", f"{width:g} in. entrance door meets the {min_width:g} in. clear width{tail}.", evidence, questions=questions)


# --------------------------------------------------------------------------------------------
# Restaurant / clinic fit-out
# --------------------------------------------------------------------------------------------


def _kitchen_fallback(ctx: EvalContext) -> list[CostNeed]:
    return [CostNeed("kitchen_install", 1, "Kitchen not confirmed; full kitchen budgeted as a precaution")]


@evaluator("kitchen_checker", fallback=_kitchen_fallback)
def kitchen_checker(ctx: EvalContext) -> EvalOutcome:
    evidence = ctx.evidence("kitchen_equipment_visible", "hood_present")
    if not ctx.requirements.needs_kitchen:
        return EvalOutcome("PASS", "No commercial kitchen required for this business.", evidence)
    has_kitchen = bool(ctx.value("kitchen_equipment_visible"))
    hood = ctx.value("hood_present")
    if not has_kitchen:
        return EvalOutcome(
            "RISK",
            "No commercial kitchen in place; a full kitchen build-out is needed.",
            evidence,
            [CostNeed("kitchen_install", 1, "No cooking line or hood observed")],
            ["Is there existing gas service and a roof penetration for a kitchen exhaust?"],
        )
    if hood is True:
        return EvalOutcome("PASS", "Existing kitchen line with an exhaust hood.", evidence)
    if hood is False:
        return EvalOutcome(
            "RISK",
            "Kitchen equipment present but no exhaust hood; a hood and fire suppression system are needed.",
            evidence,
            [CostNeed("hood_exhaust", 1, "Prep area without an exhaust hood")],
            ["Can a Type I exhaust hood be vented through the roof at this location?"],
        )
    return EvalOutcome(
        "PASS",
        "Kitchen equipment present; exhaust hood not confirmed.",
        evidence,
        questions=["Does the kitchen have a working Type I exhaust hood with fire suppression?"],
    )


def _grease_fallback(ctx: EvalContext) -> list[CostNeed]:
    return [CostNeed("grease_interceptor", 1, "Grease interceptor not confirmed; budgeted as a precaution")]


@evaluator("grease_checker", fallback=_grease_fallback)
def grease_checker(ctx: EvalContext) -> EvalOutcome:
    evidence = ctx.evidence("grease_interceptor_present")
    if ctx.value("grease_interceptor_present"):
        return EvalOutcome("PASS", "Grease interceptor in place.", evidence)
    return EvalOutcome(
        "RISK",
        "No grease interceptor observed; food service needs one before a health permit is issued.",
        evidence,
        [CostNeed("grease_interceptor", 1, "No interceptor observed")],
        ["Is there a grease interceptor on site, and when was it last pumped/inspected?"],
    )


def _operatory_fallback(ctx: EvalContext) -> list[CostNeed]:
    rooms = ctx.requirements.capacity
    return [CostNeed("operatory_plumbing", rooms, f"Plumbing not confirmed; {rooms} treatment rooms budgeted")]


@evaluator("operatory_checker", fallback=_operatory_fallback)
def operatory_checker(ctx: EvalContext) -> EvalOutcome:
    have = int(ctx.value("plumbed_operatories"))
    need = int(ctx.value("business_capacity"))
    evidence = ctx.evidence("plumbed_operatories") + [ctx.derived("business_capacity", need, "Treatment rooms needed")]
    if have >= need:
        return EvalOutcome("PASS", f"{_plural(have, 'plumbed treatment room')} for {need} needed.", evidence)
    short = need - have
    return EvalOutcome(
        "RISK",
        f"{_plural(have, 'plumbed treatment room')}; {short} more need water, vacuum and air lines.",
        evidence,
        [CostNeed("operatory_plumbing", short, f"{have} of {need} rooms plumbed")],
        ["Where are the main water and sewer lines, and can a dental vacuum/compressor room be added?"],
    )


@evaluator("bathroom_checker")
def bathroom_checker(ctx: EvalContext) -> EvalOutcome:
    have = int(ctx.value("bathrooms_visible"))
    need = int(ctx.value("business_required_bathrooms"))
    evidence = ctx.evidence("bathrooms_visible") + [
        ctx.derived("business_required_bathrooms", need, f"Restrooms needed (occupant load {ctx.requirements.occupant_load})")
    ]
    source = f"{ctx.jurisdiction.get('plumbing_code', ctx.criterion.source)} (simplified)"
    if have >= need:
        return EvalOutcome("PASS", f"{_plural(have, 'restroom')} for {need} needed.", evidence, source=source)
    short = need - have
    return EvalOutcome(
        "RISK",
        f"{_plural(have, 'restroom')} visible; {short} more needed for an occupant load of {ctx.requirements.occupant_load}.",
        evidence,
        [CostNeed("restroom_add", short, f"{have} of {need} restrooms present")],
        ["Is the existing restroom ADA-compliant, and is there plumbing capacity for another?"],
        source=source,
    )


# --------------------------------------------------------------------------------------------
# Building systems
# --------------------------------------------------------------------------------------------


def _hvac_need(ctx: EvalContext) -> float:
    """Tons needed: the larger of the stated need and conditioning this whole space."""
    per_ton = ctx.business.get("hvac_sqft_per_ton", 250)
    return round(max(float(ctx.value("required_hvac_tons") or 0), ctx.property.size_sqft / per_ton), 1)


def _hvac_fallback(ctx: EvalContext) -> list[CostNeed]:
    per_unit = float(ctx.thresholds.get("tons_per_unit", 5))
    units = max(1, math.ceil(_hvac_need(ctx) / per_unit))
    return [CostNeed("hvac_rtu", units, "Rooftop capacity unknown; new units budgeted")]


@evaluator("hvac_checker", fallback=_hvac_fallback)
def hvac_checker(ctx: EvalContext) -> EvalOutcome:
    have = float(ctx.value("hvac_tons"))
    need = _hvac_need(ctx)
    per_unit = float(ctx.thresholds.get("tons_per_unit", 5))
    per_ton = ctx.business.get("hvac_sqft_per_ton", 250)
    evidence = ctx.evidence("hvac_tons") + [
        ctx.derived("required_hvac_tons", need, f"{ctx.property.size_sqft} sq ft at {per_ton} sq ft/ton")
    ]
    if have >= need:
        return EvalOutcome("PASS", f"{have:g} tons of rooftop HVAC vs {need:g} tons needed.", evidence)
    units = math.ceil((need - have) / per_unit)
    return EvalOutcome(
        "RISK",
        f"{have:g} tons of rooftop HVAC vs {need:g} tons needed; about {_plural(units, f'{per_unit:g}-ton unit')} to add.",
        evidence,
        [CostNeed("hvac_rtu", units, f"{need - have:g} ton shortfall")],
        ["How old are the rooftop HVAC units, and who is responsible for replacement?"],
    )


def _electrical_fallback(ctx: EvalContext) -> list[CostNeed]:
    return [CostNeed("electrical_service_upgrade", 1, "Service size unknown; upgrade budgeted")]


@evaluator("electrical_checker", fallback=_electrical_fallback)
def electrical_checker(ctx: EvalContext) -> EvalOutcome:
    have = float(ctx.value("electrical_service_amps"))
    need = float(ctx.value("required_electrical_amps"))
    evidence = ctx.evidence("electrical_service_amps") + [
        ctx.derived("required_electrical_amps", int(need), f"Typical for a {ctx.requirements.business_label.lower()}")
    ]
    if have >= need:
        return EvalOutcome("PASS", f"{have:g} A service vs {need:g} A needed.", evidence)
    return EvalOutcome(
        "RISK",
        f"{have:g} A electrical service vs {need:g} A typical for this business; a service upgrade is likely.",
        evidence,
        [CostNeed("electrical_service_upgrade", 1, f"{have:g} A < {need:g} A")],
        ["What is the electrical service size, and is there utility capacity to upgrade it?"],
    )


@evaluator("fire_safety_checker")
def fire_safety_checker(ctx: EvalContext) -> EvalOutcome:
    """IBC §903.2 trigger from business_types.yaml `sprinkler_required_if`.

    A missing sprinkler system where one is required is priced as a retrofit, not treated as a
    definitive failure: sprinklers can almost always be added, so it does not hard-block.
    """
    load = int(ctx.value("occupant_load"))
    size = int(ctx.value("size_sqft"))
    rule = ctx.business.get("sprinkler_required_if")
    group = ctx.business.get("occupancy_group", "this occupancy")
    sprinklered = ctx.value("sprinklered")
    evidence = ctx.evidence("sprinklered") + [
        ctx.derived("occupant_load", load, "Estimated occupant load"),
    ]
    if not rule:
        return EvalOutcome("PASS", f"Group {group}: sprinklers not triggered by size or occupant load alone.", evidence)
    reasons = []
    if size > rule.get("sqft_over", math.inf):
        reasons.append(f"{size} sq ft > {rule['sqft_over']}")
    if load >= rule.get("occupants_at_least", math.inf):
        reasons.append(f"{load} occupants >= {rule['occupants_at_least']}")
    if not reasons:
        return EvalOutcome(
            "PASS",
            f"Group {group} sprinkler trigger not met ({size} sq ft, {load} occupants).",
            evidence,
        )
    if sprinklered is True:
        return EvalOutcome("PASS", f"Sprinklers required ({', '.join(reasons)}) and the space is sprinklered.", evidence)
    if sprinklered is False:
        return EvalOutcome(
            "RISK",
            f"Sprinklers required ({', '.join(reasons)}) but none observed; a retrofit is needed.",
            evidence,
            [CostNeed("fire_sprinkler", size, "Required by IBC §903.2, not present")],
            ["Is the building sprinklered, and is there a fire service line to the suite?"],
        )
    return EvalOutcome(
        "UNKNOWN",
        f"Sprinklers required ({', '.join(reasons)}); system not confirmed.",
        evidence,
        questions=["Is the building sprinklered, and is there a fire service line to the suite?"],
    )


# --------------------------------------------------------------------------------------------
# Marketing (added via prompts/scale-criteria.md)
# --------------------------------------------------------------------------------------------


def check_window_visibility(window_area: float, min_area: float) -> tuple[Status, str]:
    """PASS if storefront glass >= min_area sq ft, else RISK (a real, scoreable shortfall).

    Missing window data is handled by the criterion's missing_data_policy (ignore -> not scored).
    """
    if window_area >= min_area:
        return "PASS", f"{window_area:g} sq ft of street-facing glass (>= {min_area:g})."
    return "RISK", f"Only {window_area:g} sq ft of street-facing glass (< {min_area:g}); low street visibility."


@evaluator("check_window_visibility")
def window_visibility_checker(ctx: EvalContext) -> EvalOutcome:
    status, notes = check_window_visibility(float(ctx.value("window_area")), float(ctx.thresholds.get("min_area", 10)))
    questions = [] if status == "PASS" else ["Can signage be added to the storefront or a pylon sign?"]
    return EvalOutcome(status, notes, ctx.evidence("window_area"), questions=questions)
