"""Compliance / criteria agent: runs every applicable criterion against one property.

Registry semantics applied here (see criteria.yaml header):

* required_inputs missing  -> status UNKNOWN; the evaluator is not called.
* missing_data_policy      -> assume_risk: counted, scored 0
                              assume_cost: counted, scored 0, evaluator fallback cost added
                              unknown / ignore: excluded from the score
  (the same policy applies when an evaluator itself returns UNKNOWN)
* evidence_required        -> a PASS with no observed (listing / Matterport / Vexcel) evidence
                              is downgraded to UNKNOWN.
* hard_block               -> disqualifies only on a *definitive* failure. Missing data never blocks.
* unknown evaluator name   -> UNKNOWN with a note; never crashes the run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import OBSERVED_SOURCES, Criterion, CriterionResult, Evidence, Property, Requirements, Status
from .evaluators import CostNeed, EvalContext, EvalOutcome, get_evaluator
from .requirements_parser import property_parking_requirement
from .scoring import STATUS_SCORE, weighted_score

COUNTED_UNKNOWN_POLICIES = {"assume_risk", "assume_cost"}

# Human-friendly names for required inputs, used in "missing data" notes and landlord questions.
INPUT_LABELS = {
    "zoning_code": "the zoning designation",
    "visible_parking_count": "the number of parking spaces available",
    "door_width_inches": "the entrance door clear width",
    "step_free_entrance": "whether the entrance is step-free",
    "kitchen_equipment_visible": "whether commercial kitchen equipment is in place",
    "grease_interceptor_present": "whether a grease interceptor is installed",
    "plumbed_operatories": "how many treatment rooms are plumbed",
    "bathrooms_visible": "the number of restrooms",
    "hvac_tons": "the rooftop HVAC tonnage",
    "electrical_service_amps": "the electrical service size (amps)",
    "window_area": "the street-facing window area",
    "sprinklered": "whether the space is sprinklered",
    "roof_condition": "the roof condition",
}


@dataclass
class ComplianceReport:
    criteria_results: list[CriterionResult]
    cost_needs: list[CostNeed] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    disqualifiers: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return weighted_score(self.criteria_results)

    @property
    def compliance(self) -> dict[str, dict[str, str]]:
        return {r.id: {"status": r.status, "notes": r.notes, "source": r.source} for r in self.criteria_results}


def build_inputs(
    requirements: Requirements,
    prop: Property,
    observations: dict[str, Evidence],
    jurisdiction: dict[str, Any] | None = None,
    business: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Everything an evaluator may name in `required_inputs`.

    With `jurisdiction` + `business`, `business_required_parking` becomes this property's own
    requirement: the city parking minimum for its size/location (jurisdictions.yaml), never below the
    user's stated number. `code_required_parking` / `parking_requirement_note` explain it."""
    inputs: dict[str, Any] = {key: ev.value for key, ev in observations.items()}
    inputs.update(
        {
            "business_required_parking": requirements.parking_required,
            "business_required_bathrooms": requirements.bathrooms_required,
            "business_capacity": requirements.capacity,
            "required_hvac_tons": requirements.required_hvac_tons,
            "required_electrical_amps": requirements.required_electrical_amps,
            "occupant_load": requirements.occupant_load,
            "needs_kitchen": requirements.needs_kitchen,
            "size_sqft": prop.size_sqft,
            "monthly_rent": prop.rent,
            "use_restrictions": prop.use_restrictions,
        }
    )
    if jurisdiction is not None and business is not None:
        required, rule = property_parking_requirement(requirements, prop, jurisdiction, business)
        inputs["business_required_parking"] = required
        inputs["code_required_parking"] = rule.spaces
        inputs["parking_requirement_note"] = rule.note
    return inputs


def _label(key: str) -> str:
    return INPUT_LABELS.get(key, "the " + key.replace("_", " "))


def evaluate_criterion(criterion: Criterion, ctx: EvalContext) -> tuple[CriterionResult, EvalOutcome]:
    spec = get_evaluator(criterion.evaluator)
    missing = [k for k in criterion.required_inputs if ctx.inputs.get(k) is None]
    data_gap = False

    if spec is None:
        outcome = EvalOutcome(
            "UNKNOWN", f"No evaluator named '{criterion.evaluator}' is registered; criterion not evaluated."
        )
        data_gap = True
    elif missing:
        names = ", ".join(_label(k) for k in missing)
        outcome = EvalOutcome(
            "UNKNOWN",
            f"Not enough data: could not confirm {names}.",
            ctx.evidence(*criterion.required_inputs),
            questions=[f"Can you confirm {names}?"],
        )
        data_gap = True
        if criterion.missing_data_policy == "assume_cost" and spec.fallback:
            outcome.cost_items = spec.fallback(ctx)
            outcome.notes += " Fix cost included as a precaution."
    else:
        try:
            outcome = spec.func(ctx)
        except Exception as exc:  # noqa: BLE001 - a broken evaluator must not sink the whole analysis
            outcome = EvalOutcome("UNKNOWN", f"Evaluator '{criterion.evaluator}' failed: {exc}")
            data_gap = True

    if (
        outcome.status == "PASS"
        and criterion.evidence_required
        and not any(ev.source in OBSERVED_SOURCES for ev in outcome.evidence)
    ):
        outcome.status = "UNKNOWN"
        outcome.notes = f"No observed evidence to confirm: {outcome.notes}"
        outcome.cost_items = []

    status: Status = outcome.status
    if criterion.weight <= 0:
        counted, score = False, None
    elif status == "UNKNOWN":
        counted = criterion.missing_data_policy in COUNTED_UNKNOWN_POLICIES
        score = STATUS_SCORE["UNKNOWN"] if counted else None
    else:
        counted, score = True, STATUS_SCORE[status]

    blocking = bool(criterion.hard_block and status == "RISK" and outcome.definitive_failure and not data_gap)
    result = CriterionResult(
        id=criterion.id,
        description=criterion.description,
        domain=criterion.domain,
        weight=criterion.weight,
        status=status,
        score=score,
        counted=counted,
        hard_block=criterion.hard_block,
        blocking=blocking,
        notes=outcome.notes,
        source=outcome.source or criterion.source,
        evidence=outcome.evidence,
    )
    return result, outcome


def run_compliance(
    criteria: list[Criterion],
    requirements: Requirements,
    prop: Property,
    observations: dict[str, Evidence],
    jurisdiction: dict[str, Any],
    business: dict[str, Any],
) -> ComplianceReport:
    inputs = build_inputs(requirements, prop, observations, jurisdiction, business)
    report = ComplianceReport(criteria_results=[])
    for criterion in criteria:
        ctx = EvalContext(requirements, prop, observations, criterion, jurisdiction, business, inputs)
        result, outcome = evaluate_criterion(criterion, ctx)
        report.criteria_results.append(result)
        report.cost_needs.extend(outcome.cost_items)
        for q in outcome.questions:
            if q not in report.questions:
                report.questions.append(q)
        if result.blocking:
            report.disqualifiers.append(criterion.id)
        if result.status == "UNKNOWN" and criterion.missing_data_policy == "assume_cost" and outcome.cost_items:
            report.assumptions.append(f"{criterion.description}: not confirmed, so the fix is budgeted (assume_cost).")
    return report


# --------------------------------------------------------------------------------------------
# Simple helpers (prompts/02-agent-workflow.md)
# --------------------------------------------------------------------------------------------


def check_parking(visible: int | None, required: int) -> tuple[Status, str]:
    if visible is None:
        return "UNKNOWN", "Parking count not observed."
    if visible >= required:
        return "PASS", f"{visible} spaces visible vs {required} needed."
    return "RISK", f"Only {visible} spaces visible, {required} needed."


def check_ada(door_width: float | None, min_width: float = 32) -> tuple[Status, str]:
    if door_width is None:
        return "UNKNOWN", "Door width not measured."
    if door_width >= min_width:
        return "PASS", f"Door width {door_width:g} in. meets the ADA {min_width:g} in. minimum."
    return "RISK", f"Door width {door_width:g} in. is below the ADA {min_width:g} in. minimum."
