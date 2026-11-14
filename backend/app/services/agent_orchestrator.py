"""Agent pipeline behind POST /api/v1/analyze.

    1. requirements parser agent   free text -> Requirements          (regex, or Ollama / Claude)
    2. vision agent                Matterport + Vexcel + CoStar facts -> observations (Evidence by fact)
    3. compliance / criteria agent criteria.yaml evaluators -> PASS / RISK / UNKNOWN, score, blockers
    4. cost agent                  fix items -> cost ranges, TI, build-out, cost to open, first-year cost
    5. recommendation agent        rank (min-score gate), landlord questions, drafted landlord request letter
    6. explanation agent           one LLM call -> grounded ai_summary of the finished ranking (optional)

Each agent is a plain function with typed inputs/outputs so it can be tested on its own.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from ..config import cost_config, jurisdiction_for, log, settings
from ..models import (
    AnalysisResult,
    AnalyzeResponse,
    BusinessProfile,
    ComplianceStatus,
    Evidence,
    Media,
    Property,
    Requirements,
)
from ..providers import matterport_provider, vexcel_provider
from .compliance_engine import ComplianceReport, run_compliance
from .cost_engine import CostEstimate, estimate
from . import llm
from .criteria_manager import applicable_criteria
from .ranking_summary import summarize_ranking
from .requirements_parser import get_business, parse_requirements


# --------------------------------------------------------------------------------------------
# 2. Vision agent
# --------------------------------------------------------------------------------------------


def _to_evidence(key: str, raw: Any, source: str) -> Evidence:
    if isinstance(raw, dict) and "value" in raw:
        return Evidence(
            key=key, value=raw["value"], source=source, note=raw.get("note"),
            confidence=raw.get("confidence"), box=raw.get("box"),
        )
    return Evidence(key=key, value=raw, source=source)


def gather_observations(prop: Property) -> tuple[dict[str, Evidence], Media]:
    """Merge listing facts (CoStar), interior facts (Matterport) and aerial facts (Vexcel).

    Live Vexcel facts (property/extract) win over fixture aerial facts of the same key;
    fixture facts still fill any gaps."""
    interior = matterport_provider.get_interior(prop)
    aerial = vexcel_provider.get_aerial(prop)

    observations: dict[str, Evidence] = {}
    if prop.zoning:
        observations["zoning_code"] = Evidence(
            key="zoning_code", value=prop.zoning, source="costar", note="Zoning from the listing", confidence=0.95
        )
    if prop.previous_use:
        observations["previous_use"] = Evidence(
            key="previous_use", value=prop.previous_use, source="costar", note="Prior tenant use from the listing"
        )
    observations["size_sqft"] = Evidence(key="size_sqft", value=prop.size_sqft, source="costar", note="Leasable area")
    for key, raw in interior["observations"].items():
        observations[key] = _to_evidence(key, raw, "matterport")
    # Boxes only line up with the image they were drawn for. Live / snapshot Vexcel facts are
    # positioned on the live ortho image, so they are dropped over the placeholder SVG; hand-made
    # fixture boxes were drawn for the placeholder SVG, so they are dropped over live imagery.
    placeholder = aerial["aerial_source"] == "placeholder"
    for key, raw in aerial["observations"].items():
        ev = _to_evidence(key, raw, "vexcel")
        snapshot = vexcel_provider.is_snapshot_fact(raw)
        if ev.box is not None and (placeholder == snapshot):
            ev = ev.model_copy(update={"box": None})
        observations[key] = ev
    for key, ev in aerial["live_observations"].items():
        observations[key] = ev.model_copy(update={"box": None}) if placeholder and ev.box is not None else ev

    media = Media(
        aerial_url=aerial["aerial_url"],
        oblique_url=aerial["oblique_url"],
        floor_plan_url=interior["floor_plan_url"],
        matterport_embed_url=interior["matterport_embed_url"],
        image_url=prop.image_url,
        aerial_source=aerial["aerial_source"],
        aerial_attribution=aerial["aerial_attribution"],
    )
    return observations, media


# --------------------------------------------------------------------------------------------
# 5. Recommendation agent
# --------------------------------------------------------------------------------------------


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _money_range(lo: float, hi: float) -> str:
    return _money(lo) if round(lo) == round(hi) else f"{_money(lo)}-{_money(hi)}"


def landlord_questions(report: ComplianceReport, costs: CostEstimate, prop: Property) -> list[str]:
    questions = list(report.questions)
    has_improvements = costs.hard_costs.max > 0
    if has_improvements and costs.net_fit_out.max > 0:
        questions.append(
            f"Would you increase the TI allowance (currently {_money(costs.ti_allowance)}) toward an estimated "
            f"{_money_range(costs.fit_out.min, costs.fit_out.max)} fit-out?"
        )
    questions.append(
        f"Can you offer free rent during the estimated {costs.buildout_months.min:g}-{costs.buildout_months.max:g} "
        "month build-out?"
    )
    seen: set[str] = set()
    return [q for q in questions if not (q in seen or seen.add(q))]


def draft_landlord_request(
    requirements: Requirements, prop: Property, report: ComplianceReport, costs: CostEstimate
) -> str:
    """Template-based plain-text letter. Deterministic so it can be stored and diffed."""
    unit = requirements.capacity_unit
    lines = [
        f"Subject: Lease inquiry and tenant improvement request - {prop.address}",
        "",
        "Hello,",
        "",
        f"We are evaluating {prop.address}, {prop.city}, {prop.state} ({prop.size_sqft:,} sq ft, "
        f"{_money(prop.rent)}/month) for a {requirements.capacity}-{unit.rstrip('s')} "
        f"{requirements.business_label.lower()}. Before signing, we would like to discuss the following.",
        "",
    ]
    hard = [i for i in costs.line_items if i.item in cost_config()["items"]]
    if hard:
        lines.append("Improvements the space needs for our use (preliminary estimates):")
        for item in hard:
            qty = f" x{item.qty:g}" if item.qty != 1 and item.qty < 100 else ""
            lines.append(f"  - {item.label}{qty}: {_money_range(item.min, item.max)} ({item.reason})")
        lines += [
            "",
            f"Including permits, general conditions and contingency, we estimate the fit-out at "
            f"{_money_range(costs.fit_out.min, costs.fit_out.max)}.",
            "",
            "Our requests:",
            f"  1. A tenant improvement allowance covering this work (the listing shows "
            f"{_money(costs.ti_allowance)}), or landlord completion of the items above before delivery.",
            f"  2. Rent abatement during the estimated {costs.buildout_months.min:g}-{costs.buildout_months.max:g} "
            "month build-out.",
        ]
    else:
        lines += [
            "The space appears to fit our needs largely as-is, which is why it is at the top of our list.",
            "",
            "Our requests:",
            f"  1. Rent abatement during the estimated {costs.buildout_months.min:g}-{costs.buildout_months.max:g} "
            "month setup period.",
            "  2. Confirmation that existing HVAC, plumbing, electrical and any kitchen systems are in working order at delivery.",
        ]
    open_items = [q for q in report.questions][:6]
    if open_items:
        lines += ["", "Could you also help us with these questions?"]
        lines += [f"  - {q}" for q in open_items]
    lines += [
        "",
        "These figures are preliminary estimates, not contractor quotes. We look forward to your reply.",
        "",
        "Thank you,",
        "[Your name]",
        "[Business name] | [Phone] | [Email]",
    ]
    return "\n".join(lines)


def ranking_settings() -> tuple[int, float]:
    """(horizon_months, min_score) from the `ranking:` section of costs.yaml."""
    ranking = cost_config().get("ranking") or {}
    return int(ranking.get("horizon_months", 12)), float(ranking.get("min_score", 0) or 0)


def rank_results(results: list[AnalysisResult], min_score: float = 0) -> list[AnalysisResult]:
    """Three tiers, each cheapest first-year cost first with ties broken by higher score:
    qualifying (score >= min_score), weak fit (score < min_score), then disqualified.
    Sets `weak_fit` and `rank` on each result."""
    for result in results:
        result.weak_fit = not result.disqualified and result.score < min_score

    def key(r: AnalysisResult) -> tuple:
        tier = 2 if r.disqualified else 1 if r.weak_fit else 0
        return (tier, r.first_year_cost.min, r.first_year_cost.max, -r.score)

    ordered = sorted(results, key=key)
    for rank, result in enumerate(ordered, start=1):
        result.rank = rank
    return ordered


def ranking_basis(horizon: int, min_score: float) -> str:
    cost = f"first-year cost (cost to open + {horizon} months rent)"
    if min_score <= 0:
        return f"Ranked by {cost}; disqualified properties last; ties broken by criteria score."
    return (
        f"Ranked by {cost} among properties with a fit score of at least {min_score:g}; "
        f"weak fits (score below {min_score:g}) next, then disqualified properties; "
        "ties broken by criteria score."
    )


# --------------------------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------------------------


def analyze_property(requirements: Requirements, prop: Property) -> AnalysisResult:
    business = get_business(requirements.business_type)
    jurisdiction = jurisdiction_for(prop.city, prop.state)
    criteria = applicable_criteria(requirements.business_type, prop.city, prop.state)

    observations, media = gather_observations(prop)
    report = run_compliance(criteria, requirements, prop, observations, jurisdiction, business)
    costs = estimate(report.cost_needs, prop, business)

    assumptions = report.assumptions + costs.assumptions
    if jurisdiction["key"] == "default":
        assumptions.append(f"No local rules loaded for {prop.city}, {prop.state}; model codes used.")
    low_conf = [ev.key for ev in observations.values() if ev.confidence is not None and ev.confidence < 0.7]
    if low_conf:
        assumptions.append("Low-confidence observations (verify on site): " + ", ".join(sorted(low_conf)) + ".")

    return AnalysisResult(
        property_id=prop.id,
        address=prop.address,
        listing_source=prop.listing_source,
        use_restrictions=prop.use_restrictions,
        rank=0,
        score=report.score,
        disqualified=bool(report.disqualifiers),
        disqualifiers=report.disqualifiers,
        monthly_rent=prop.rent,
        total_cost_estimate=costs.cost_to_open,
        first_year_cost=costs.first_year,
        fit_out_estimate=costs.fit_out,
        ti_allowance=costs.ti_allowance,
        buildout_months=costs.buildout_months,
        breakdown=costs.breakdown,
        line_items=costs.line_items,
        compliance={k: ComplianceStatus(**v) for k, v in report.compliance.items()},
        criteria_results=report.criteria_results,
        questions_for_landlord=landlord_questions(report, costs, prop),
        landlord_request=draft_landlord_request(requirements, prop, report, costs),
        observations=observations,
        media=media,
        assumptions=assumptions,
    )


def analyze_properties(profile: BusinessProfile, properties: list[Property]) -> AnalyzeResponse:
    started = time.perf_counter()
    requirements, parser_used = parse_requirements(profile)
    parsed = time.perf_counter()
    horizon, min_score = ranking_settings()
    results = rank_results([analyze_property(requirements, prop) for prop in properties], min_score)
    ranked = time.perf_counter()
    response = AnalyzeResponse(
        analysis_id=uuid.uuid4().hex,
        created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        business_type=requirements.business_type,
        requirements=requirements,
        ranking_basis=ranking_basis(horizon, min_score),
        min_score=min_score,
        results=results,
        mode={**settings.mode_summary, "parser": parser_used, "llm": "none"},
        disclaimer=" ".join(str(cost_config().get("disclaimer", "")).split()),
    )
    # 6. Explanation agent: one grounded LLM call over the finished ranking (None on any failure).
    response.ai_summary = summarize_ranking(response)
    if parser_used != "regex" or response.ai_summary is not None:
        response.mode["llm"] = llm.label()
    log.info(
        "analysis timings: parse %.2fs (%s), evaluate+rank %.2fs, summary %.2fs (%s), total %.2fs",
        parsed - started, parser_used, ranked - parsed, time.perf_counter() - ranked,
        "ok" if response.ai_summary else "none", time.perf_counter() - started,
    )
    return response
