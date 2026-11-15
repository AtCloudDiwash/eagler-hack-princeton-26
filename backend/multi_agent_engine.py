"""Coordinates the property investigation.

  1. Gather context (property, neighborhood, census, jurisdiction) concurrently.
  2. Plan which agents are needed and why.
  3. Phase 1 (concurrent): Vexcel, Neighborhood, Compliance (+ Matterport if available).
  4. Share their findings with the Cost Agent (phase 2), which depends on them.
  5. Validate: evidence citations (an agent may only cite what it saw), metric verdicts settled by data
     (services/verdicts.py: verified rules, the cost engine, the CoStar building record, aerial and interior
     data — agents may be more cautious, never less), "not detected" never treated as a blocker.
  6. Detect contradictions between agents and resolve them with explicit precedence.
  7. Targeted follow-ups for unknown, high-weight metrics whose resolution could change the verdict.
  8. Score in Python, then ask the LLM for a narrative grounded in the scored results.
A failing agent never fails the analysis: its metrics become "unknown" and confidence drops. Only when every
LLM provider is exhausted does the analysis stop. Everything runs inside one deadline (ANALYSIS_TIMEOUT_S).
"""
from __future__ import annotations

import asyncio
import re
import inspect
import json
import logging
import time
from typing import Any, Literal

from pydantic import BaseModel, Field

import db
from agents import compliance_agent, cost_agent, matterport_agent, neighborhood_agent, vexcel_agent
from agents.base import AGENT_LABELS, EvidenceStore, RunContext
from config import business, metrics_registry, settings
from schemas import AgentMetricAssessment, AgentReport, AnalysisRequest, MetricResult
from services import costs as cost_engine
from services import external, matterport, neighborhood, rules, scoring
from services import program as space_program
from services import verdicts as verdict_engine
from services.geo import haversine_m
from services.intent import combine_request, refine, target_sqft
from services.llm import AllProvidersFailedError, chat_model, model_label, on_fallback, track_usage
from services.vexcel import key_facts, imagery_meta

log = logging.getLogger("turnkey.engine")
MAX_FOLLOWUPS = 2
FOLLOWUP_AGENTS = {"vexcel": vexcel_agent, "neighborhood": neighborhood_agent, "compliance": compliance_agent, "matterport": matterport_agent}


class EventLog:
    FLUSH_EVERY_S = 0.4  # progress is polled by the UI; batching keeps DB writes linear instead of one per event

    def __init__(self, analysis_id: str) -> None:
        self.analysis_id = analysis_id
        self.start = time.time()
        self.events: list[dict] = []
        self._flushed = 0.0

    def emit(self, agent: str, type_: str, message: str, data: dict | None = None) -> None:
        self.events.append({"t": round(time.time() - self.start, 1), "agent": agent, "type": type_, "message": message, "data": data})
        if type_ in {"start", "done", "error", "skipped", "followup"} or time.time() - self._flushed >= self.FLUSH_EVERY_S:
            self.flush()

    def flush(self) -> None:
        self._flushed = time.time()
        db.update_analysis(self.analysis_id, events=list(self.events))


# ---------------------------------------------------------------- context

async def build_context(req: AnalysisRequest, prop: dict, feature: dict | None, log_: EventLog) -> RunContext:
    intent = req.intent.model_dump()
    cfg = business(intent["business_type"])
    lat, lon = prop["lat"], prop["lon"]
    fetch_radius = max(req.radius_m, cfg["default_radius_m"])
    log_.emit("engine", "plan", f"Gathering context: neighbors within {fetch_radius} m, places, census tract, jurisdiction")

    nb_task = neighborhood.build(lat, lon, req.radius_m, exclude_id=prop["id"])
    feats_task = neighborhood.neighbor_buildings(lat, lon, fetch_radius, exclude_id=prop["id"])
    census_task = external.census_profile(lat, lon)
    rev_task = external.reverse(lat, lon)
    nb, (summaries, raws, _), census, rev = await asyncio.gather(nb_task, feats_task, census_task, rev_task)
    for s, f in zip(summaries, raws):
        f["_distance_m"] = s["distance_m"]
    nb["fetched_radius_m"] = fetch_radius
    nb["user_radius_m"] = req.radius_m
    prop = {**prop, "address": prop.get("address") or rev.get("address"), "city": rev.get("city"), "state": rev.get("state")}
    jkey, jur = rules.jurisdiction_for(rev.get("city"), rev.get("state"))
    sq, basis = target_sqft(req.intent)
    building: dict = {}
    try:
        from services import building_facts  # CoStar building record + Vexcel attributes as named facts

        building = building_facts.facts(prop, feature) or {}
    except Exception as err:  # noqa: BLE001 - facts are an enrichment; the analysis runs without them
        log.warning("building facts unavailable: %s", err)
    return RunContext(
        query=req.query,
        intent=intent,
        property=prop,
        feature=feature,
        neighborhood=nb,
        neighbor_features=raws,
        census=census,
        jurisdiction_key=jkey,
        jurisdiction=jur,
        target_sqft=sq,
        target_basis=basis,
        extra_requirements=req.requirements,
        mode=req.mode,
        evidence=EvidenceStore(),
        emit=log_.emit,
        program=space_program.build(req.intent),
        deadline=log_.start + settings.analysis_timeout_s,
        building=building,
    )


# ---------------------------------------------------------------- validation & conflicts

def _evidence_data(ctx: RunContext, tool: str) -> list[tuple[str, Any]]:
    return [(e.id, e.data) for e in ctx.evidence.all() if e.tool == tool]


def metric_tools(mid: str) -> tuple[str, ...]:
    """Tools whose results support a metric (config/metrics.yaml `evidence_tools`)."""
    return tuple(metrics_registry().get(mid, {}).get("evidence_tools") or ())


def _relevant(mid: str, e: Any) -> bool:
    data = e.data if isinstance(e.data, dict) else {}
    if e.tool == "count_places":
        role = data.get("role_for_business")
        return (mid == "competition" and role == "competitors") or (mid == "customer_demand" and role == "demand")
    if e.tool == "inspect_roof":
        keys = " ".join(data)
        return ("ac-unit" in keys or "roof-vent" in keys) if mid == "hvac_ventilation" else ("condition" in keys or "defects" in keys)
    return e.data is not None


def merge_metrics(ctx: RunContext, reports: dict[str, AgentReport], log_: EventLog) -> tuple[list[MetricResult], list[dict]]:
    """Combine agent assessments with the data-settled verdicts into metric results, and record conflicts.

    Verdicts are computed once per analysis (services/verdicts.settle); combining them with the agents'
    assessments is pure, so merging again after follow-ups gives a consistent result."""
    reg = metrics_registry()
    verdicts = verdict_engine.settle(ctx)
    conflicts: list[dict] = []
    assessed: dict[str, tuple[str, AgentMetricAssessment]] = {}
    for agent, rep in reports.items():
        for a in rep.metric_assessments:
            if a.status == "unknown" and a.metric_id in assessed:
                continue  # a gap filled with 'unknown' never replaces a real assessment
            assessed[a.metric_id] = (agent, a)

    # Agents sometimes run the right tool but forget to cite it. Link evidence from the tools that a metric
    # depends on (same agent only), and log it so the dashboard shows the link was made by the engine.
    for mid, (owner, a) in list(assessed.items()):
        if a.evidence_ids or a.status == "unknown":
            continue
        tools = metric_tools(mid)
        linked = [e.id for e in ctx.evidence.all() if e.agent == owner and e.tool in tools and _relevant(mid, e)]
        if linked:
            assessed[mid] = (owner, a.model_copy(update={"evidence_ids": linked}))
            log_.emit("engine", "validation", f"{reg[mid]['name']}: {AGENT_LABELS[owner]} cited no evidence; linked {', '.join(linked)} from the tool(s) it ran")

    merged: dict[str, tuple[str, AgentMetricAssessment]] = {}
    overridden: dict[str, str] = {}
    for mid in [*assessed, *[m for m in verdicts if m not in assessed]]:
        if mid not in reg:
            continue
        owner, a = assessed.get(mid, (reg[mid]["owner"], None))
        result, conflict = verdict_engine.apply(mid, owner, a, verdicts.get(mid), AGENT_LABELS[owner])
        if result is None:
            continue
        merged[mid] = (result.owner, result.assessment)
        if result.overridden:
            overridden[mid] = result.assessment.status
        if conflict:
            v = verdicts[mid]
            conflicts.append({"description": f"{reg[mid]['name']}: {conflict}", "agents": [owner, "engine"], "resolution": f"Set to '{v.status}' — verified rules, the cost engine and recorded building data take precedence over agent judgment (an agent may only be more cautious)."})
            log_.emit("engine", "validation", f"{reg[mid]['name']}: '{a.status if a else 'none'}' → '{v.status}' ({v.source})")

    # "Not detected" is never a blocker: a blocker without evidence (or on a metric that cannot block) is downgraded.
    for mid, (owner, a) in list(merged.items()):
        if a.status == "blocker" and (not a.evidence_ids or not reg.get(mid, {}).get("hard_block")):
            reason = "a blocker needs direct evidence of impossibility (or this metric cannot block)"
            conflicts.append({"description": f"{reg[mid]['name']}: {AGENT_LABELS[owner]} said 'blocker', but {reason}", "agents": [owner, "engine"], "resolution": "Set to 'weak'."})
            log_.emit("engine", "validation", f"{reg[mid]['name']}: 'blocker' → 'weak' ({reason})")
            merged[mid] = (owner, a.model_copy(update={"status": "weak"}))
            overridden[mid] = "weak"
    ctx.shared["overridden_metrics"] = overridden

    # Cross-agent contradiction: on-site parking looks fine but the legal minimum is not met.
    op, pr = merged.get("onsite_parking"), merged.get("parking_requirement")
    if op and pr and op[1].status in {"strong", "adequate"} and pr[1].status == "weak":
        conflicts.append({"description": "Vexcel Agent rated on-site parking acceptable, but the Compliance Agent found the legal minimum is likely not met.", "agents": ["vexcel", "compliance"], "resolution": "Both kept: practical parking may suffice for customers, but the permit risk stands until a parking agreement or variance is confirmed."})

    results: list[MetricResult] = []
    valid = ctx.evidence.ids()
    for mid, mcfg in ctx.business["metrics"].items():
        m = reg.get(mid)
        if not m:
            continue
        owner, a = merged.get(mid, (m["owner"], None))
        if mid == "evidence_quality":
            continue  # computed after scoring
        if a is None:
            rep = reports.get(m["owner"])
            why = "agent failed" if rep and rep.status == "failed" else "not assessed"
            a = AgentMetricAssessment(metric_id=mid, status="unknown", rationale=f"No assessment ({why}).")
        eids = [e for e in a.evidence_ids if e in valid]
        results.append(MetricResult(
            id=mid, name=m["name"], category=m["category"], group=m["group"], owner_agent=owner, weight=mcfg["weight"], status=a.status,
            score=scoring.metric_score(a.status, bool(eids)), why_it_matters=mcfg["why"], rationale=a.rationale,
            evidence_ids=eids, facts=a.facts, assumptions=a.assumptions,
        ))
    return results, conflicts


def reconcile_findings(reports: dict[str, AgentReport], metrics: list[MetricResult], overridden: dict[str, str]) -> None:
    """Drop agent findings that argue the opposite of a metric the engine settled (e.g. "Permitted use: strong"
    after the verified rule says otherwise), so risks, the Cost Agent's inputs and the dashboard stay consistent."""
    if not overridden:
        return
    for rep in reports.values():
        kept = []
        for f in rep.findings:
            linked = [m for m in f.metric_ids if m in overridden]
            if linked and len(linked) == len(f.metric_ids):
                status = overridden[linked[0]]
                if (f.impact == "positive" and status in {"weak", "blocker"}) or (f.impact == "negative" and status == "strong"):
                    continue
            kept.append(f)
        rep.findings = kept


def must_have_gaps(ctx: RunContext, reports: dict[str, AgentReport], checks: list[dict]) -> list[str]:
    """Must-have needs the evidence shows are not met (a site check at 'risk' or an evidenced 'unmet')."""
    musts = {n["id"]: n for n in (ctx.program or {}).get("needs", []) if n["priority"] == "must"}
    gaps = []
    for nid, n in musts.items():
        check = next((c for c in checks if c["id"] == nid), None)
        unmet = next((x for r in reports.values() for x in r.needs if x.need_id == nid and x.status == "unmet" and x.evidence_ids), None)
        if (check and check["status"] == "risk") or unmet:
            gaps.append(f"{n['label']}: {check['detail'] if check and check['status'] == 'risk' else unmet.detail}")
    return gaps


def _scoring_rows(metrics: list[MetricResult]) -> list[dict]:
    reg = metrics_registry()
    return [{"id": m.id, "weight": m.weight, "status": m.status, "score": m.score, "evidence_ids": m.evidence_ids, "hard_block": reg[m.id].get("hard_block", False)} for m in metrics]


def followup_candidates(ctx: RunContext, metrics: list[MetricResult], reports: dict[str, AgentReport]) -> list[MetricResult]:
    """Unknown/unverified metrics whose resolution could flip the verdict, owned by an agent that can dig further."""
    base = scoring.overall(_scoring_rows(metrics))["verdict"]
    settled = {mid for mid, v in ctx.shared.get("verdicts", {}).items() if v.kind == "authoritative"}
    out = []
    for m in sorted(metrics, key=lambda m: -m.weight):
        if m.id in settled:
            continue  # already decided by data; another LLM pass cannot change it
        if m.owner_agent not in FOLLOWUP_AGENTS or reports.get(m.owner_agent, AgentReport(agent=m.owner_agent, label="", status="failed")).status in {"failed", "skipped"}:
            continue
        if not (m.status == "unknown" or (m.score is not None and not m.evidence_ids)) or m.weight < 6:
            continue
        verdicts = set()
        for trial in ("strong", "weak"):
            rows = [{**r, "status": trial, "score": float(scoring.STATUS_POINTS[trial]), "evidence_ids": ["E?"]} if r["id"] == m.id else r for r in _scoring_rows(metrics)]
            verdicts.add(scoring.overall(rows)["verdict"])
        if verdicts != {base}:
            out.append(m)
    # Then: important metrics left unknown although no relevant evidence was ever gathered for them.
    for m in sorted(metrics, key=lambda m: -m.weight):
        tools = metric_tools(m.id)
        if m in out or m.id in settled or m.status != "unknown" or m.weight < 5 or not tools:
            continue
        if reports.get(m.owner_agent) is None or reports[m.owner_agent].status in {"failed", "skipped"}:
            continue
        if not any(e.agent == m.owner_agent and e.tool in tools and _relevant(m.id, e) for e in ctx.evidence.all()):
            out.append(m)
    return out[:MAX_FOLLOWUPS]


# ---------------------------------------------------------------- synthesis

class _RequirementCheck(BaseModel):
    requirement: str
    status: Literal["met", "unmet", "unknown"] = Field(description="met/unmet only with direct evidence; otherwise unknown")
    rationale: str = Field(description="One sentence; for unknown, say how to verify")
    evidence_ids: list[str] = Field(default_factory=list)


class _RequirementChecks(BaseModel):
    checks: list[_RequirementCheck]


def need_checks(ctx: RunContext, reports: dict[str, AgentReport], checks: list[dict]) -> list[dict]:
    """The space program's needs as requirement checks: the owning agent's evidenced report wins, otherwise the
    deterministic site check (pass -> met, risk -> unmet), otherwise unknown."""
    out = []
    for n in (ctx.program or {}).get("needs", []):
        rep = next((x for r in reports.values() for x in r.needs if x.need_id == n["id"] and x.status != "unknown" and x.evidence_ids), None)
        site = next((c for c in checks if c["id"] == n["id"] and c["status"] != "unknown"), None)
        if rep:
            status, why, ids = rep.status, rep.detail, rep.evidence_ids
        elif site:
            status, why, ids = ("met" if site["status"] == "pass" else "unmet"), site["detail"], []
        else:
            status, why, ids = "unknown", "Not settled by the gathered evidence; verify on a site visit or with the landlord.", []
        out.append({"requirement": n["label"], "status": status, "rationale": why, "evidence_ids": ids, "priority": n["priority"], "need_id": n["id"]})
    return out


_STOP = {"a", "an", "the", "and", "or", "of", "to", "for", "with", "near", "good", "nearby", "lots", "some", "space", "area"}


def _covered(requirement: str, labels: set[str]) -> bool:
    words = {w for w in re.findall(r"[a-z]+", requirement.lower()) if w not in _STOP}
    return any(requirement.lower() in label or label in requirement.lower() or words & {w for w in re.findall(r"[a-z]+", label) if w not in _STOP} for label in labels)


async def requirement_checks(ctx: RunContext, reports: dict[str, AgentReport] | None = None, metrics: list[MetricResult] | None = None, skip: set[str] | None = None) -> list[dict]:
    """Judge each need the user stated (search prompt + extra requirements) against the gathered evidence and
    the agents' cited findings. Python validates citations: met/unmet without real evidence becomes unknown."""
    needs = [r for r in ctx.intent.get("requirements") or [] if r.strip() and not _covered(r, skip or set())]
    if not needs:
        return []  # everything was covered by the space program's needs: no extra LLM call
    evidence = "\n".join(f"{e.id} [{e.tool}]: {e.summary}" for e in ctx.evidence.all())
    findings = "\n".join(
        f"- [{name}] {f.title}: {f.detail} (evidence {', '.join(f.evidence_ids) or 'none'})"
        for name, r in (reports or {}).items() for f in r.findings
    )
    judged = "\n".join(f"- {m.name}: {m.status}. {m.rationale[:200]} (evidence {', '.join(m.evidence_ids) or 'none'})" for m in metrics or [] if m.status != "unknown")
    prompt = (
        f"User's request: \"{ctx.query}\"\n"
        "For EACH stated requirement below, decide whether the selected property meets it. Use the evidence and the "
        "agents' cited findings and metric judgments; cite evidence ids. Use 'met' or 'unmet' only when evidence "
        "supports it (an agent finding counts if it cites evidence); otherwise 'unknown' and say how to verify it.\n"
        f"Requirements: {json.dumps(needs)}\n\nAGENT FINDINGS:\n{findings or '(none)'}\n\nMETRIC JUDGMENTS:\n{judged or '(none)'}"
        f"\n\nEVIDENCE:\n{evidence}"
    )
    valid = ctx.evidence.ids()
    try:
        out: _RequirementChecks = await asyncio.wait_for(chat_model().with_structured_output(_RequirementChecks).ainvoke(prompt), timeout=120)
        checks = {c.requirement.lower(): c for c in out.checks}
    except Exception as err:  # noqa: BLE001 - checks are best effort; every need still appears as unknown
        log.warning("requirement checks failed: %s", err)
        checks = {}
    result = []
    for need in needs:
        c = checks.get(need.lower()) or next((v for k, v in checks.items() if need.lower() in k or k in need.lower()), None)
        if c is None:
            result.append({"requirement": need, "status": "unknown", "rationale": "Could not be evaluated from the gathered evidence.", "evidence_ids": []})
            continue
        ids = [e for e in c.evidence_ids if e in valid]
        status = c.status if (c.status == "unknown" or ids) else "unknown"
        result.append({"requirement": need, "status": status, "rationale": c.rationale, "evidence_ids": ids})
    return result


class _Narrative(BaseModel):
    headline: str = Field(description="One specific sentence about THIS property for THIS business (not just the verdict label), e.g. naming the decisive strength and the main risk")
    explanation: str = Field(description="3-5 sentences: why, the decisive factors, and what to verify next. Only use facts given.")


async def narrative(ctx: RunContext, rec: dict, metrics: list[MetricResult], reports: dict[str, AgentReport], costs: dict | None, req_checks: list[dict] | None = None) -> tuple[str, str]:
    digest = {
        "user_request": ctx.query,
        "address": ctx.property.get("address"),
        "verdict": rec["label"],
        "score": rec["score"],
        "confidence": rec["confidence"],
        "metrics": [{"name": m.name, "status": m.status, "weight": m.weight, "rationale": m.rationale[:220]} for m in sorted(metrics, key=lambda m: -m.weight)],
        "agent_summaries": {k: r.summary for k, r in reports.items() if r.summary},
        "costs": {"upfront": costs["upfront"], "monthly": costs["monthly_occupancy"]} if costs else None,
        "budget": costs.get("budget") if costs else None,
        "user_requirements": [{"requirement": c["requirement"], "status": c["status"], "why": c["rationale"]} for c in req_checks or []],
        "verdict_caps": rec.get("caps", []),
    }
    prompt = (
        "You are the lead analyst. Write the final recommendation for the user from this scored analysis. "
        "Judge it against what the user asked for: their request and stated requirements come first. "
        "The headline must be specific to this property and business, in the form '<decisive strength(s)>, but <main risk or unknown>', in your own words; "
        "if a stated requirement or budget is unmet, that IS the main risk and must be named. "
        "In the explanation, say plainly which of the user's requirements are met, unmet or still unverified, then the 2-3 other decisive factors "
        "and the most important thing to verify. Do not change the verdict (verdict_caps explains any cap) or invent numbers.\n"
        + json.dumps(digest, default=str)
    )
    try:
        llm = chat_model().with_structured_output(_Narrative, method="json_schema")
        out: _Narrative = await asyncio.wait_for(llm.ainvoke(prompt), timeout=ctx.time_left(150))
        return out.headline, out.explanation
    except Exception as err:  # noqa: BLE001
        log.warning("narrative failed: %s", err)
        top = sorted([m for m in metrics if m.status != "unknown"], key=lambda m: -m.weight)[:3]
        needs = " ".join(f"Your requirement '{c['requirement']}': {c['status']}." for c in req_checks or [])
        caps = " ".join(rec.get("caps", []))
        return (
            f"{rec['label']} for a {ctx.business['label'].lower()} (score {rec['score']}, confidence {rec['confidence']}%).",
            " ".join(x for x in (caps, needs, " ".join(f"{m.name}: {m.status}." for m in top)) if x) + " (Narrative generation unavailable; summary built from scored metrics.)",
        )


def key_reasons(metrics: list[MetricResult]) -> list[dict]:
    ranked = sorted([m for m in metrics if m.score is not None and m.weight > 0], key=lambda m: -m.weight * abs(m.score - 55))
    out = []
    for m in ranked[:6]:
        impact = "positive" if m.score >= 60 else "negative"
        out.append({"text": f"{m.name}: {m.rationale}", "impact": impact, "metric_id": m.id, "evidence_ids": m.evidence_ids})
    for m in sorted([m for m in metrics if m.status == "unknown" and m.weight >= 8], key=lambda m: -m.weight)[:2]:
        out.append({"text": f"Not yet verified — {m.name}: {m.rationale}", "impact": "negative", "metric_id": m.id, "evidence_ids": []})
    return out


def site_checks(ctx: RunContext) -> list[dict]:
    return space_program.site_checks(ctx.program, space_program.facts_from(ctx.property, ctx.feature, ctx.building))


def compliance_items(ctx: RunContext) -> list[dict]:
    items: dict[str, dict] = {}
    for e in ctx.evidence.all():
        if e.tool in {"check_permitted_use", "compute_parking_requirement", "check_flood_zone"} and isinstance(e.data, dict):
            d = e.data
            items[d["id"]] = {"id": d["id"], "rule": d["rule"], "status": d["status"], "detail": d["detail"], "citation": d.get("citation"), "url": d.get("url"), "evidence_ids": [e.id]}
        if e.tool == "list_use_requirements" and isinstance(e.data, dict):
            for d in e.data["items"]:
                items[d["id"]] = {**d, "evidence_ids": [e.id]}
    if not any(e.tool == "list_use_requirements" for e in ctx.evidence.all()):
        for d in rules.use_requirements(ctx.jurisdiction, ctx.intent["business_type"]):
            items.setdefault(d["id"], {**d, "evidence_ids": []})
    # what the user's program triggers at this building (always shown; cites the agent's evidence when it ran the check)
    prog_ev = [e.id for e in ctx.evidence.all() if e.tool == "check_space_program"]
    for row in space_program.compliance_rows(ctx.program, site_checks(ctx)):
        items.setdefault(row["id"], {**row, "evidence_ids": prog_ev[-1:]})
    order = {"fail": 0, "risk": 1, "unknown": 2, "pass": 3}
    return sorted(items.values(), key=lambda i: order.get(i["status"], 9))


# ---------------------------------------------------------------- main entry

async def run_analysis(analysis_id: str, req: AnalysisRequest) -> None:
    log_ = EventLog(analysis_id)
    db.update_analysis(analysis_id, status="running")
    llm_counts = track_usage()
    on_fallback(lambda msg: log_.emit("engine", "validation", msg))
    try:
        stored = db.get_property(req.property_id)
        if not stored:
            raise ValueError(f"Unknown property {req.property_id}")
        prop, feature = stored
        if req.requirements and req.requirements.strip():
            # One request everywhere: search prompt + what the user added before Analyze (re-parsed for budget,
            # seats, size and needs). Stored so the dashboard and history show the full request.
            log_.emit("engine", "plan", f"Adding your extra requirements to the request: \u201c{req.requirements.strip()[:120]}\u201d")
            refined = await refine(req.intent, req.query, req.requirements)
            req = req.model_copy(update={"intent": refined, "query": combine_request(req.query, req.requirements)})
            db.update_analysis(analysis_id, query=req.query, intent=json.dumps(refined.model_dump()))
        ctx = await build_context(req, prop, feature, log_)
        db.update_analysis(analysis_id, property=json.dumps({**ctx.property, "key_facts": key_facts(feature), "raw": feature, "imagery": imagery_meta(feature), "matterport": matterport.link_info(ctx.property)}))

        # ---- plan
        mp_ok, mp_reason = matterport_agent.available(ctx)
        plan = [
            ("vexcel", "run" if feature else "skip", "Investigate building characteristics from Vexcel" if feature else "No Vexcel data for this building"),
            ("neighborhood", "run", f"Catchment ~{ctx.business['default_radius_m']} m for a {ctx.business['label'].lower()}"),
            ("compliance", "run", f"Rules for {ctx.jurisdiction['name']}"),
            ("matterport", "run" if mp_ok else "skip", f"Interior from Matterport scan {ctx.property['matterport_model_id']}" if mp_ok else mp_reason),
            ("cost", "run", "After building + compliance findings (depends on them)"),
        ]
        for agent, action, why in plan:
            log_.emit("engine", "plan", f"{AGENT_LABELS[agent]}: {'will run' if action == 'run' else 'skipped'} — {why}")

        reports: dict[str, AgentReport] = {}

        def collect(names: list[str], results: list) -> None:
            limit_hit = next((r for r in results if isinstance(r, AllProvidersFailedError) and r.exhausted), None)
            if limit_hit:
                raise limit_hit  # every provider is out: nothing more can be investigated
            for name, rep in zip(names, results):
                if isinstance(rep, BaseException):
                    log_.emit(name, "error", f"Crashed: {rep}")
                    reports[name] = AgentReport(agent=name, label=AGENT_LABELS[name], status="failed", error=str(rep))
                else:
                    reports[name] = rep

        def share_upstream(names: tuple[str, ...]) -> int:
            lines, shared_ids = [], set()
            for name in names:
                r = reports.get(name)
                if not r:
                    continue
                for f in r.findings:
                    if f.impact == "negative" or f.severity != "low":
                        lines.append(f"- [{AGENT_LABELS[name]}] {f.title}: {f.detail} (evidence {', '.join(f.evidence_ids) or 'none'}; {f.kind})")
                        shared_ids.update(f.evidence_ids)
                for q in r.missing_information[:3]:
                    lines.append(f"- [{AGENT_LABELS[name]}] UNKNOWN: {q}")
            ctx.shared["upstream_findings"] = "\n".join(lines[:24])
            ctx.shared["visible:cost"] = shared_ids  # the Cost Agent may cite the evidence behind the findings it was given
            return len(lines)

        async def run_cost() -> AgentReport:
            try:
                return await cost_agent.run(ctx)
            except AllProvidersFailedError as err:
                if err.exhausted:
                    raise
                return AgentReport(agent="cost", label=AGENT_LABELS["cost"], status="failed", error=str(err))
            except Exception as err:  # noqa: BLE001
                return AgentReport(agent="cost", label=AGENT_LABELS["cost"], status="failed", error=str(err))

        if ctx.mode == "quick":
            # Quick: agents start from pre-gathered evidence. The Cost agent only needs the building and rules
            # evidence (not the other agents' write-ups), so it starts as soon as that evidence exists.
            log_.emit("engine", "plan", "Quick mode: agents start from pre-gathered evidence; Cost starts once building + rules evidence is in")
            for name in ("vexcel", "compliance"):
                ctx.shared[f"prefetched:{name}"] = asyncio.Event()
            tasks = {name: asyncio.create_task(mod.run(ctx)) for name, mod in
                     (("vexcel", vexcel_agent), ("compliance", compliance_agent), ("neighborhood", neighborhood_agent), ("matterport", matterport_agent))}

            async def evidence_ready(name: str) -> None:
                waiter = asyncio.create_task(ctx.shared[f"prefetched:{name}"].wait())
                await asyncio.wait({tasks[name], waiter}, return_when=asyncio.FIRST_COMPLETED)  # finished/skipped also counts
                waiter.cancel()

            await asyncio.gather(evidence_ready("vexcel"), evidence_ready("compliance"))
            upstream = [e for e in ctx.evidence.all() if e.agent in ("vexcel", "compliance")]
            ctx.shared["upstream_findings"] = "\n".join(f"- [{AGENT_LABELS[e.agent]}] {e.id} {e.tool}: {e.summary}" for e in upstream[:24])
            ctx.shared["visible:cost"] = {e.id for e in upstream}
            log_.emit("engine", "plan", f"Cost Agent starts with {len(upstream)} evidence items from Vexcel + Compliance")
            t_cost = asyncio.create_task(run_cost())
            order = ["vexcel", "compliance", "neighborhood", "matterport"]
            collect(order, await asyncio.gather(*(tasks[n] for n in order), return_exceptions=True))
            collect(["cost"], [(await asyncio.gather(t_cost, return_exceptions=True))[0]])
        else:
            # ---- phase 1: independent investigations, concurrently
            log_.emit("engine", "plan", "Phase 1: Vexcel, Neighborhood, Compliance" + (" and Matterport" if mp_ok else "") + " agents investigating in parallel")
            collect(
                ["vexcel", "neighborhood", "compliance", "matterport"],
                await asyncio.gather(vexcel_agent.run(ctx), neighborhood_agent.run(ctx), compliance_agent.run(ctx), matterport_agent.run(ctx), return_exceptions=True),
            )
            # ---- share findings with the dependent Cost Agent
            n = share_upstream(("vexcel", "compliance", "matterport", "neighborhood"))
            log_.emit("engine", "plan", f"Phase 2: Cost Agent receives {n} upstream findings")
            reports["cost"] = await run_cost()

        # Guarantee a cost estimate exists (deterministic, no adders) if the agent never produced one.
        if not _evidence_data(ctx, "estimate_costs"):
            data = cost_engine.estimate(ctx.intent["business_type"], ctx.target_sqft, ctx.jurisdiction_key, [])
            data["sqft_basis"] = f"{ctx.target_sqft:,} sq ft ({ctx.target_basis}); no conversion items (Cost Agent produced no estimate)"
            ctx.evidence.add("engine", "estimate_costs", "Deterministic cost engine", "Baseline estimate without conversion items", data)
            log_.emit("engine", "validation", "Cost Agent produced no estimate; added a baseline engine estimate")

        # ---- validate + merge
        metrics, conflicts = merge_metrics(ctx, reports, log_)

        # ---- targeted follow-ups that could change the recommendation
        followups_run = []
        for m in followup_candidates(ctx, metrics, reports) if ctx.mode == "deep" else []:
            if ctx.deadline and ctx.deadline - time.time() < 120:
                log_.emit("engine", "followup", f"Skipped follow-up on {m.name}: not enough time left before the analysis deadline")
                break
            agent_mod = FOLLOWUP_AGENTS[m.owner_agent]
            question = f"Resolve the metric '{m.id}' ({m.name}). It is currently '{m.status}' and could change the final verdict. Find specific evidence or confirm it cannot be determined."
            log_.emit("engine", "followup", f"Follow-up to {AGENT_LABELS[m.owner_agent]}: {m.name} could change the verdict")
            try:
                kwargs = {"metric_ids": [m.id]} if "metric_ids" in inspect.signature(agent_mod.run).parameters else {}
                rep = await agent_mod.run(ctx, budget_limit=3, focus=question, **kwargs)
            except AllProvidersFailedError as err:
                if err.exhausted:
                    raise
                followups_run.append({"agent": m.owner_agent, "question": question, "outcome": f"Failed: {err}"})
                continue
            except Exception as err:  # noqa: BLE001
                followups_run.append({"agent": m.owner_agent, "question": question, "outcome": f"Failed: {err}"})
                continue
            new = next((a for a in rep.metric_assessments if a.metric_id == m.id), None)
            orig = reports[m.owner_agent]
            if new and new.status != "unknown" and new.evidence_ids:
                orig.metric_assessments = [a for a in orig.metric_assessments if a.metric_id != m.id] + [new]
                orig.findings += [f.model_copy(update={"id": f"{f.id}-fu"}) for f in rep.findings[:2]]
                outcome = f"Resolved: '{m.status}' → '{new.status}' ({new.rationale[:160]})"
            else:
                outcome = "Still unresolved after follow-up; kept as an open question."
            orig.tool_calls += rep.tool_calls
            followups_run.append({"agent": m.owner_agent, "question": question, "outcome": outcome})
            log_.emit("engine", "followup", outcome)
        if followups_run:
            metrics, conflicts = merge_metrics(ctx, reports, log_)
        reconcile_findings(reports, metrics, ctx.shared.get("overridden_metrics", {}))

        # ---- the user's needs and budgets, judged BEFORE scoring so they count
        cost_data = _evidence_data(ctx, "estimate_costs")[-1][1]  # the agent's estimate, or the engine's program-size recompute
        cost_public = {k: v for k, v in cost_data.items() if not k.startswith("_")}
        budgets = cost_engine.budget_checks(cost_data, ctx.intent, ctx.intent["business_type"])
        primary = ctx.intent.get("budget")
        cost_public["budget"] = next((c for c in budgets if primary and c["period"] == primary["period"]), budgets[0])
        cost_public["budgets"] = budgets  # every stated budget (e.g. monthly and upfront), each checked
        checks = site_checks(ctx)
        gaps = must_have_gaps(ctx, reports, checks)
        # Needs from the space program are reported by the agents; only requirements it doesn't cover need an LLM check.
        req_checks = need_checks(ctx, reports, checks)
        covered = {c["requirement"].lower() for c in req_checks}
        req_checks += await requirement_checks(ctx, reports, metrics, skip=covered)
        if req_checks:
            log_.emit("engine", "validation", "Checked your stated needs — " + ", ".join(f"{c['requirement']}: {c['status']}" for c in req_checks))

        # ---- score (Python): metrics + your needs, then caps for unmet must-haves / blown budgets
        rec = scoring.overall(_scoring_rows(metrics) + scoring.requirement_rows(req_checks))
        rec = scoring.cap_for_requirements(rec, req_checks, budgets)
        if gaps and rec["verdict"] == "recommended":
            rec = {**rec, "verdict": "conditional", "label": scoring.VERDICT_LABELS["conditional"], "caps": [*rec["caps"], *(f"Must-have not met — {g}" for g in gaps)]}
        for reason in rec["caps"]:
            log_.emit("engine", "validation", f"Verdict capped at '{rec['label']}': {reason[:200]}")
        if "evidence_quality" in ctx.business["metrics"]:
            eq = scoring.evidence_quality_status(rec["confidence"])
            metrics.append(MetricResult(id="evidence_quality", name="Evidence quality", category="common", group="Confidence", owner_agent="engine", weight=0, status=eq, score=float(scoring.STATUS_POINTS[eq]), why_it_matters=ctx.business["metrics"]["evidence_quality"]["why"], rationale=f"{rec['confidence']}% of the weighted metrics are backed by verified evidence.", evidence_ids=[]))
        log_.emit("engine", "validation", f"Scored {len(metrics)} metrics in Python: score {rec['score']}, confidence {rec['confidence']}% → {rec['label']}")

        log_.emit("engine", "thinking", "Writing the final recommendation from the scored results")
        headline, explanation = await narrative(ctx, rec, metrics, reports, cost_public, req_checks)

        reg = metrics_registry()
        risks = []
        for name, r in reports.items():
            for f in r.findings:
                if f.impact == "negative" and f.severity in {"medium", "high"}:
                    risks.append({"text": f"{f.title}: {f.detail}", "severity": f.severity, "agent": name})
        for c in req_checks:
            if c["status"] == "unmet":
                risks.append({"text": f"Your requirement not met — {c['requirement']}: {c['rationale']}", "severity": "high", "agent": "engine"})
        risks.sort(key=lambda r: 0 if r["severity"] == "high" else 1)
        open_questions = []
        for name, r in reports.items():
            for i, q in enumerate(r.missing_information):
                open_questions.append({"question": q, "why": f"Raised by the {AGENT_LABELS[name]}", "suggested_source": r.followups[i] if i < len(r.followups) else "Site visit / ask the landlord", "agent": name})
        nb = ctx.neighborhood
        highlights = [f"{v} {k.lower()}" for k, v in list(nb.get("place_groups", {}).items())[:5]]
        data_sources = [
            {"name": "Vexcel property data", "status": "used" if feature and prop.get("source") == "vexcel" else "demo" if feature else "unavailable", "note": "AI roof/site attributes for the building and neighbors" if feature else "No Vexcel data for this building"},
            *nb.get("sources", [])[1:],
            {"name": "US Census ACS", "status": ctx.census.get("status", "unavailable"), "note": ctx.census.get("note", "")},
            {"name": "Verified jurisdiction rules", "status": "used" if ctx.jurisdiction_key != "_default" else "unavailable", "note": ctx.jurisdiction["name"]},
            *[{"name": f"LLM: {model_label(p)}", "status": "used" if llm_counts.get(p) else "unavailable",
               "note": f"{llm_counts.get(p, 0)} calls" + (" (fallback)" if llm_counts.get(p) and p != settings.llm_providers[0] else "")}
              for p in settings.llm_providers],
            {"name": "Matterport interior scan", "status": "used" if mp_ok else "unavailable", "note": mp_reason or f"Model API ({matterport.data_mode(ctx.property['matterport_model_id'])}), model {ctx.property['matterport_model_id']}"},
            {"name": "CoStar building & listings", "status": "used" if (ctx.building.get("costar_id") or ctx.property.get("costar_id")) else "unavailable",
             "note": "Building record (year built, class, parking, sprinklers…) and lease listings from the CoStar kit snapshot" if (ctx.building.get("costar_id") or ctx.property.get("costar_id")) else "No CoStar record matched this building; rent uses documented planning bands"},
        ]
        result = {
            "business_type": ctx.intent["business_type"],
            "mode": ctx.mode,
            "requirement_checks": req_checks,
            "business_label": ctx.business["label"],
            "recommendation": {
                "verdict": rec["verdict"], "label": rec["label"], "score": rec["score"], "confidence": rec["confidence"],
                "headline": headline, "explanation": explanation,
                "key_reasons": [*({"text": f"Must-have not met — {g}", "impact": "negative", "metric_id": None, "evidence_ids": []} for g in gaps), *key_reasons(metrics)],
                "dealbreakers": [f"{reg[b]['name']} is a blocker" for b in rec["blockers"]] + [c for c in rec["caps"] if not c.startswith("Must-have not met")],
            },
            "metrics": [m.model_dump() for m in metrics],
            "agents": [reports[a].model_dump() for a in ("vexcel", "neighborhood", "compliance", "cost", "matterport") if a in reports],
            "evidence": [e.model_dump() for e in ctx.evidence.all()],
            "costs": cost_public,
            "compliance": compliance_items(ctx),
            "program": ctx.program,
            "site_checks": checks,
            "neighborhood": {
                **{k: v for k, v in nb.items() if k not in {"fetched_radius_m", "user_radius_m"}},
                "radius_reason": ctx.business["radius_reason"].strip(),
                "highlights": highlights,
            },
            "risks": risks[:12],
            "open_questions": open_questions[:14],
            "conflicts": conflicts,
            "followups_run": followups_run,
            "data_sources": data_sources,
        }
        db.update_analysis(analysis_id, status="completed", result=result)
        log_.emit("engine", "done", f"Analysis complete in {time.time() - log_.start:.0f}s")
    except Exception as err:  # noqa: BLE001
        log.exception("analysis %s failed", analysis_id)
        log_.emit("engine", "error", f"Analysis failed: {err}")
        db.update_analysis(analysis_id, status="failed", error=str(err))
    finally:
        log_.flush()
