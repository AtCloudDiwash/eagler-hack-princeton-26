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
    verify              True on an UNKNOWN that is a "verify with the landlord" finding (the data
                        exists but cannot settle the question, e.g. a prorated share of building-level
                        HVAC). The compliance engine excludes it from the score whatever the
                        criterion's `missing_data_policy`.

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
from .requirements_parser import property_parking_requirement


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
    verify: bool = False  # UNKNOWN to verify (not a data gap): excluded from the score, see module docstring
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


def _use_restriction_evidence(ctx: EvalContext) -> list[Evidence]:
    """The listing's disclosed use restrictions as an observed (CoStar listing) fact, if the listing says."""
    restrictions = ctx.property.use_restrictions
    if restrictions is None:
        return []
    note = "Use restrictions disclosed in the listing" if restrictions else "Listing discloses no use restrictions"
    return [Evidence(key="use_restrictions", value=list(restrictions), source="costar", note=note)]


def _blocking_use_restriction(ctx: EvalContext, use: str) -> str | None:
    """First disclosed restriction tag that prohibits `use` (jurisdictions.yaml `use_restriction_blocks`)."""
    blocks = ctx.jurisdiction.get("use_restriction_blocks") or {}
    for tag in ctx.property.use_restrictions or []:
        if use in (blocks.get(str(tag).strip().lower()) or []):
            return str(tag)
    return None


@evaluator("zoning_checker")
def zoning_checker(ctx: EvalContext) -> EvalOutcome:
    """Land-use check, config-driven per jurisdiction (jurisdictions.yaml):

    1. A disclosed deed / lease use restriction that prohibits the use -> RISK, definitive (any city).
    2. `zoning_mode: none` (e.g. Houston) -> PASS with the city's `zoning_note` (verify deed restrictions).
    3. `zoning_mode: districts` -> look the listing's zoning code up in the city's use table.
    """
    use = ctx.business.get("zoning_use", ctx.requirements.business_type)
    label = ctx.requirements.business_label.lower()
    city = ctx.jurisdiction.get("name", "this city")
    source = ctx.jurisdiction.get("zoning_source") or ctx.criterion.source
    restriction_evidence = _use_restriction_evidence(ctx)

    blocking = _blocking_use_restriction(ctx, use)
    if blocking:
        return EvalOutcome(
            "RISK",
            f"Recorded use restriction '{blocking}' on this property prohibits {use.replace('_', ' ')} use; "
            "a deed or lease restriction can't be permitted around, so the space is ruled out.",
            restriction_evidence
            + [ctx.derived("use_restriction_rule", f"{blocking}: prohibits {use}", f"{city} use-restriction rules", "jurisdiction")],
            questions=[f"Can the '{blocking}' restriction be released or amended for a {label}?"],
            definitive_failure=True,
            source=ctx.jurisdiction.get("use_restriction_source") or source,
        )

    if ctx.jurisdiction.get("zoning_mode") == "none":
        note = " ".join(str(ctx.jurisdiction.get("zoning_note") or f"{city} has no zoning; verify deed restrictions.").split())
        return EvalOutcome(
            "PASS",
            note,
            restriction_evidence + [ctx.derived("zoning_mode", "no zoning", note, "jurisdiction")],
            questions=[f"Are there recorded deed restrictions or lease use clauses that limit a {label} at this property?"],
            source=" ".join(str(source).split()),
        )

    if ctx.value("zoning_code") is None:
        return EvalOutcome(
            "UNKNOWN",
            "Not enough data: could not confirm the zoning designation.",
            restriction_evidence,
            questions=[f"What is the zoning designation, and does it permit a {label} use?"],
            source=source,
        )
    code = str(ctx.value("zoning_code")).strip().upper()
    table = (ctx.jurisdiction.get("zoning") or {}).get(use)
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


def _parking_basis(ctx: EvalContext, required: float) -> tuple[str, str, list[Evidence]]:
    """(basis phrase for the spaces needed, citation for the result's `source`, rule evidence).

    The requirement comes from the user, the city code (config/jurisdictions.yaml parking_ratios,
    with market-based / exempt areas) or the business guideline; the phrase says which, and the
    evidence cites the jurisdiction's parking rule (source "jurisdiction")."""
    rule = property_parking_requirement(ctx.requirements, ctx.property, ctx.jurisdiction, ctx.business)[1]
    city = ctx.jurisdiction.get("name", "This city")
    cite = ctx.jurisdiction.get("parking_ratio_cite") or rule.source or "city code"
    stated = ctx.requirements.parking_required
    from_user = ctx.requirements.parking_source == "user"
    general_note = " ".join(str(ctx.jurisdiction.get("parking_note") or "").split())

    if rule.spaces is None:  # the city sets no minimum for this use: user number or guideline
        basis = "you stated" if from_user else "business guideline, not a code minimum"
        value = "no minimum loaded" if ctx.jurisdiction.get("parking_minimums") else "no parking minimum"
        evidence = [ctx.derived("parking_rule", value, general_note or f"{city}: no parking minimum loaded", "jurisdiction")]
        return basis, general_note or ctx.criterion.source, evidence

    if rule.spaces == 0:  # exempt / market-based area
        where = f"no {city} parking minimum in the {rule.exempt_area}"
        basis = f"you stated; {where}" if from_user and required > 0 else where
        evidence = [ctx.derived("parking_rule", f"no minimum ({rule.exempt_area})", rule.note, "jurisdiction")]
        return basis, rule.source or general_note, evidence

    ratio = f"{rule.ratio:g} per 1,000 sq ft"
    if not from_user:
        basis = f"{cite}: {ratio}"
    elif rule.spaces > stated and required >= rule.spaces:  # the city minimum raised the user's number
        basis = f"you stated {stated}; {cite} ({ratio}) raises it to {rule.spaces}"
    else:
        basis = f"you stated; {cite} minimum is {rule.spaces}"
    evidence = [
        ctx.derived("code_required_parking", rule.spaces, rule.note, "jurisdiction"),
        ctx.derived("parking_rule", f"{ratio} GFA", rule.source or cite, "jurisdiction"),
    ]
    return basis, rule.source or general_note, evidence


def _vehicles_context(ctx: EvalContext) -> list[Evidence]:
    """Vehicles seen on the aerial image: context only, never used as a space count."""
    return [
        ev.model_copy(update={"note": f"{ev.note or 'Vehicles visible'} (context only, not a count of available spaces)"})
        for ev in ctx.evidence("vehicles_count")
    ]


@evaluator("parking_checker")
def parking_checker(ctx: EvalContext) -> EvalOutcome:
    """Visible (striped) parking count when known; otherwise the Vexcel estimate from paved area.

    The provider omits the estimate when parcel paving is under one space (urban parcels with shared
    or street parking), so missing both -> UNKNOWN (scored per the criterion's missing_data_policy).
    `vehicles_count` is shown as context only."""
    required = float(ctx.value("business_required_parking"))
    min_ratio = float(ctx.thresholds.get("min_ratio", 1.0))
    basis, source, rule_evidence = _parking_basis(ctx, required)
    needed = [ctx.derived("business_required_parking", int(required), f"Spaces needed ({basis})")] + rule_evidence
    context = _vehicles_context(ctx)
    if ctx.value("visible_parking_count") is not None:
        count, fact, label = float(ctx.value("visible_parking_count")), "visible_parking_count", "visible"
    elif ctx.value("estimated_parking_spaces") is not None:
        count, fact, label = float(ctx.value("estimated_parking_spaces")), "estimated_parking_spaces", "estimated"
    else:
        paved = ctx.value("paved_area_sqft")
        detail = (
            f" Parcel paving is only {float(paved):,.0f} sq ft (less than one space), so parking is likely a shared lot or the street."
            if paved is not None else ""
        )
        return EvalOutcome(
            "UNKNOWN",
            f"Not enough data: could not confirm the number of parking spaces available ({int(required)} needed: {basis}).{detail}",
            ctx.evidence("paved_area_sqft") + context + needed,
            questions=["Can you confirm the number of parking spaces available?"],
            source=source,
        )
    facts = (fact, "paved_area_sqft") if label == "estimated" else (fact,)
    evidence = ctx.evidence(*facts) + context + needed
    caveat = " (estimated from paved area, not a striped-space count)" if label == "estimated" else ""
    if required <= 0:
        return EvalOutcome("PASS", f"No spaces required ({basis}); {count:g} spaces {label}{caveat}.", evidence, source=source)
    if count / required >= min_ratio:
        return EvalOutcome("PASS", f"{count:g} spaces {label} vs {required:g} needed ({basis}){caveat}.", evidence, source=source)
    return EvalOutcome(
        "RISK",
        f"Only {count:g} spaces {label} vs {required:g} needed ({basis}){caveat}.",
        evidence,
        questions=[f"How many of the {count:g} {label} parking spaces are reserved for this unit, and is overflow parking available nearby?"],
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
    # Cite the city's own grease rule when the jurisdiction config has one (Austin, Houston, ...).
    local = ctx.jurisdiction.get("grease_code")
    source = " ".join(str(local).split()) if local else None
    if ctx.value("grease_interceptor_present"):
        return EvalOutcome("PASS", "Grease interceptor in place.", evidence, source=source)
    return EvalOutcome(
        "RISK",
        "No grease interceptor observed; food service needs one before a health permit is issued.",
        evidence,
        [CostNeed("grease_interceptor", 1, "No interceptor observed")],
        ["Is there a grease interceptor on site, and when was it last pumped/inspected?"],
        source=source,
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


def _hvac_suite_share(ctx: EvalContext, building_tons: float) -> Evidence | None:
    """The listing's share of building-level rooftop tonnage, when `prorate_by_footprint` is on and
    the Vexcel building footprint is known and larger than the listing:

        tons x min(1, size_sqft / building_footprint_sqft)

    None otherwise (fixture tonnage without a footprint is taken as the suite's own)."""
    footprint = ctx.value("building_footprint_sqft")
    size = ctx.property.size_sqft
    if not ctx.thresholds.get("prorate_by_footprint") or not footprint or float(footprint) <= size:
        return None
    share = min(1.0, size / float(footprint))
    units = ctx.value("rooftop_hvac_units")
    what = _plural(int(units), "rooftop unit") if units is not None else f"{building_tons:g} tons of rooftop HVAC"
    building = ctx.observations.get("hvac_tons")
    return Evidence(
        key="hvac_tons_suite_share",
        value=round(building_tons * share, 1),
        source="vexcel",
        note=f"≈ your share of {what} ({float(footprint):,.0f} sq ft building, {size:,} sq ft suite): "
        f"{building_tons:g} tons x {size:,} / {float(footprint):,.0f}",
        live=bool(building and building.live),
    )


HVAC_VERIFY_QUESTION = "Which rooftop HVAC units serve this suite, and what is their tonnage and age?"


@evaluator("hvac_checker", fallback=_hvac_fallback)
def hvac_checker(ctx: EvalContext) -> EvalOutcome:
    """Rooftop tonnage vs the space's need.

    * direct tonnage (fixture value, or footprint unknown / not larger than the suite): short -> RISK
      with new-unit cost.
    * building-level tonnage prorated to the suite (`prorate_by_footprint`): a short share is UNKNOWN
      with `verify` (excluded from the score, no unit cost, landlord question) — the share is an
      estimate, and the building's units may well serve this suite. Zero detected rooftop units
      (or zero building tons) is still RISK with cost.
    """
    building_tons = float(ctx.value("hvac_tons"))
    need = _hvac_need(ctx)
    per_unit = float(ctx.thresholds.get("tons_per_unit", 5))
    per_ton = ctx.business.get("hvac_sqft_per_ton", 250)
    units = ctx.value("rooftop_hvac_units")
    # hvac_tons is a fixture observation or, live, Vexcel rooftop units x tons_per_unit (whole building).
    evidence = ctx.evidence("hvac_tons", "rooftop_hvac_units")
    share = _hvac_suite_share(ctx, building_tons)
    if share is not None:
        have = float(share.value)
        evidence += ctx.evidence("building_footprint_sqft") + [share]
        what = _plural(int(units), "rooftop unit") if units is not None else f"{building_tons:g} building tons"
        capacity = (
            f"≈{_plural(have, 'ton')} of rooftop HVAC (your share of {what}: "
            f"{float(ctx.value('building_footprint_sqft')):,.0f} sq ft building, {ctx.property.size_sqft:,} sq ft suite)"
        )
    else:
        have = building_tons
        capacity = f"{have:g} tons of rooftop HVAC"
    evidence.append(ctx.derived("required_hvac_tons", need, f"{ctx.property.size_sqft} sq ft at {per_ton} sq ft/ton"))
    if have >= need:
        return EvalOutcome("PASS", f"{capacity} vs {need:g} tons needed.", evidence)

    no_units = building_tons <= 0 or (units is not None and int(units) == 0)
    if share is not None and not no_units:
        building = (
            f"Building has {_plural(int(units), 'rooftop unit')} (≈{building_tons:g} tons total)"
            if units is not None
            else f"Building has ≈{building_tons:g} tons of rooftop HVAC"
        )
        return EvalOutcome(
            "UNKNOWN",
            f"{building}; your prorated share ≈{_plural(have, 'ton')} vs {need:g} needed — "
            "ask the landlord which units serve your suite.",
            evidence,
            questions=[HVAC_VERIFY_QUESTION],
            verify=True,
        )

    units_to_add = math.ceil(round(need - have, 1) / per_unit)
    to_add = f"about {_plural(units_to_add, f'{per_unit:g}-ton unit')} to add"
    if no_units:
        return EvalOutcome(
            "RISK",
            f"No rooftop HVAC units detected on the building vs {need:g} tons needed; {to_add}.",
            evidence,
            [CostNeed("hvac_rtu", units_to_add, "No rooftop HVAC detected")],
            ["Is this suite served by any HVAC (rooftop, split or ground units), and who is responsible for it?"],
        )
    return EvalOutcome(
        "RISK",
        f"{capacity} vs {need:g} tons needed; {to_add}.",
        evidence,
        [CostNeed("hvac_rtu", units_to_add, f"{round(need - have, 1):g} ton shortfall")],
        ["How old are the rooftop HVAC units, which of them serve this suite, and who is responsible for replacement?"],
    )


DEFAULT_SERIOUS_ROOF_DEFECTS = ("structural-damage", "tarp")


@evaluator("roof_checker")
def roof_checker(ctx: EvalContext) -> EvalOutcome:
    """Vexcel AI roof condition (1-5) and detected defects. A tarp or structural damage is a RISK
    regardless of the condition score. Never a definitive failure: roofs can be repaired."""
    condition = float(ctx.value("roof_condition"))
    min_condition = float(ctx.thresholds.get("min_condition", 3))
    serious_names = ctx.thresholds.get("serious_defects", DEFAULT_SERIOUS_ROOF_DEFECTS)
    defects = [str(d) for d in (ctx.value("roof_defects") or [])]
    serious = [d for d in defects if d in serious_names]
    evidence = ctx.evidence("roof_condition", "roof_defects", "roof_material", "building_footprint")
    if condition >= min_condition and not serious:
        others = f"; minor defects: {', '.join(defects)}" if defects else ""
        return EvalOutcome("PASS", f"Roof condition {condition:g}/5 (needs {min_condition:g}+){others}.", evidence)
    problems = []
    if condition < min_condition:
        problems.append(f"roof condition {condition:g}/5 is below {min_condition:g}")
    if serious:
        problems.append(f"{', '.join(d.replace('-', ' ') for d in serious)} detected from aerial imagery")
    return EvalOutcome(
        "RISK",
        "Roof risk: " + "; ".join(problems) + ". Budget a repair/recoat unless the landlord fixes it.",
        evidence,
        [CostNeed("roof_repair", ctx.property.size_sqft, "; ".join(problems))],
        ["When was the roof last replaced or recoated, and is roof repair the landlord's responsibility under the lease?"],
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
