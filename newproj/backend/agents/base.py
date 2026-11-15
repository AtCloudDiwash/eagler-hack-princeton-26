"""Shared agent harness: LangChain Deep Agents on the LLM fallback chain (Codex → Claude Code → Ollama), evidence tracking, bounded tool use,
structured output with a constrained-JSON fallback, and live progress events.

Every tool result is registered as evidence with an id (E1, E2...). Agents must cite those ids; the
engine later rejects citations that don't exist. Tools refuse repeated identical calls and stop
working once the agent's budget is spent, so investigations stay purposeful.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from deepagents import GeneralPurposeSubagentProfile, HarnessProfile, create_deep_agent, register_harness_profile
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool

from config import business, metrics_registry, settings
from schemas import AgentFinding, AgentMetricAssessment, AgentOutput, AgentReport, Evidence, Finding
from services.llm import AllProvidersFailedError, chat_model

log = logging.getLogger("turnkey.agents")

# Deep Agents ships file-system, shell, todo and sub-agent tools. Our agents investigate through their
# own domain tools only; extra tools waste steps and add prompt tokens to every call.
_LEAN = dict(
    excluded_tools=frozenset({"ls", "read_file", "write_file", "edit_file", "glob", "grep", "execute", "task", "write_todos"}),
    general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
)
# "turnkey" = FallbackChat (Codex → Claude Code → Ollama); the others cover direct provider use.
for _provider in ("turnkey", "codex", "claude", "ollama"):
    register_harness_profile(_provider, HarnessProfile(**_LEAN))

AGENT_LABELS = {
    "vexcel": "Vexcel Agent",
    "neighborhood": "Neighborhood Agent",
    "compliance": "Compliance Agent",
    "cost": "Cost Agent",
    "matterport": "Matterport Agent",
    "engine": "Multi-agent engine",
}


class EvidenceStore:
    def __init__(self) -> None:
        self._items: list[Evidence] = []
        self._lock = threading.Lock()

    def add(self, agent: str, tool: str, source: str, summary: str, data: Any, url: str | None = None) -> str:
        with self._lock:
            eid = f"E{len(self._items) + 1}"
            self._items.append(Evidence(id=eid, agent=agent, tool=tool, source=source, url=url, summary=summary, data=data))
            return eid

    def ids(self) -> set[str]:
        return {e.id for e in self._items}

    def get(self, eid: str) -> Evidence | None:
        return next((e for e in self._items if e.id == eid), None)

    def by_agent(self, agent: str) -> list[Evidence]:
        return [e for e in self._items if e.agent == agent]

    def all(self) -> list[Evidence]:
        return list(self._items)


@dataclass
class RunContext:
    """Everything an investigation knows. Built by multi_agent_engine.py."""

    query: str
    intent: dict
    property: dict  # Candidate dict (+ address)
    feature: dict | None  # full Vexcel feature for the selected parcel
    neighborhood: dict  # services.neighborhood.build() output
    neighbor_features: list[dict]
    census: dict
    jurisdiction_key: str
    jurisdiction: dict
    target_sqft: int
    target_basis: str
    extra_requirements: str | None
    evidence: EvidenceStore
    emit: Callable[[str, str, str, dict | None], None]
    shared: dict[str, Any] = field(default_factory=dict)  # findings shared between agents
    mode: str = "deep"  # "quick" = pre-gathered evidence, fewer model calls, brief reports; "deep" = full investigation

    @property
    def business(self) -> dict:
        return business(self.intent["business_type"])

    def metrics_for(self, agent: str) -> list[dict]:
        """This business's metrics owned by `agent`, with business-specific reasons, highest weight first."""
        reg = metrics_registry()
        out = []
        for mid, cfg in self.business["metrics"].items():
            m = reg.get(mid)
            if m and m["owner"] == agent:
                out.append({"id": mid, **m, "weight": cfg["weight"], "why": cfg["why"]})
        return sorted(out, key=lambda m: -m["weight"])


class ToolBudget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0
        self.seen: dict[str, str] = {}


def tracked_tool(ctx: RunContext, agent: str, budget: ToolBudget, source: str) -> Callable[[Callable[..., dict]], StructuredTool]:
    """Decorator: turns a function returning {summary, data, url?} into a LangChain tool that registers
    evidence, emits events, refuses duplicate calls and enforces the budget."""

    def wrap(fn: Callable[..., dict]) -> StructuredTool:
        @functools.wraps(fn)
        def runner(**kwargs: Any) -> str:
            key = f"{fn.__name__}:{json.dumps(kwargs, sort_keys=True, default=lambda o: o.model_dump() if hasattr(o, 'model_dump') else str(o))}"
            if key in budget.seen:
                return json.dumps({"note": f"Already called with these arguments; see evidence {budget.seen[key]}. Use that result."})
            if budget.used >= budget.limit:
                return json.dumps({"note": "Tool budget exhausted. Stop investigating and return your structured report now."})
            budget.used += 1
            safe_args = json.loads(json.dumps(kwargs, default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o)))
            shown = ", ".join(f"{k}={json.dumps(v) if isinstance(v, (list, dict)) else v}" for k, v in safe_args.items())
            ctx.emit(agent, "tool_call", f"{fn.__name__}({shown[:200]})", {"tool": fn.__name__, "args": safe_args})
            try:
                result = fn(**kwargs)
            except Exception as err:  # noqa: BLE001 - surface tool errors to the agent as data
                log.exception("tool %s failed", fn.__name__)
                ctx.emit(agent, "error", f"{fn.__name__} failed: {err}", None)
                return json.dumps({"error": str(err)})
            eid = ctx.evidence.add(agent, fn.__name__, result.get("source", source), result["summary"], result.get("data"), result.get("url"))
            budget.seen[key] = eid
            ctx.emit(agent, "tool_result", f"{eid}: {result['summary']}", {"evidence_id": eid, "tool": fn.__name__, "args": safe_args})
            payload = {"evidence_id": eid, "summary": result["summary"], **({"data": result["data"]} if result.get("data") is not None else {})}
            if result.get("guidance"):
                payload["interpretation_notes"] = result["guidance"]
            return json.dumps(payload, default=str)

        runner.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
        return StructuredTool.from_function(func=runner, name=fn.__name__, description=inspect.getdoc(fn) or fn.__name__)

    return wrap


def metrics_brief(metrics: list[dict]) -> str:
    lines = []
    for m in metrics:
        guide = "; ".join(f"{k}: {v}" for k, v in m["status_guide"].items())
        lines.append(
            f"- {m['id']} — {m['name']} (weight {m['weight']})\n"
            f"  Why it matters for this user: {m['why']}\n"
            f"  Evidence to look for: {m['evidence_hint']}\n"
            f"  Status guide: {guide}"
        )
    return "\n".join(lines)


COMMON_RULES = """How to investigate:
1. Start from the user's actual goal. Decide which of your metrics matter most for THIS business and what evidence would settle each one.
2. Call a tool only when it can add evidence you need. Never repeat a call. Budget: at most {budget} tool calls.
3. If a result raises an important question, investigate it with a more specific tool call; otherwise move on.
4. Every metric assessment and finding must cite evidence ids (like E3) from YOUR tool results or the shared context. Do not cite ids you did not see.
5. Separate facts (directly in tool data) from inferences (your reasoning) and assumptions (gaps you filled).
6. "Not detected in imagery" is NOT the same as "absent". Treat it as an open question and say how to verify it.
7. If evidence is insufficient, use status "unknown", add the question to missing_information, and suggest how to resolve it in followups.
8. Explain why each finding matters for the user's specific business, not in general.
9. Finish by returning your structured report (AgentOutput) with one metric assessment per assigned metric id."""


QUICK_RULES = """
QUICK MODE (the user asked for a fast answer):
- The key evidence for your metrics is already gathered below the request (cite its E-ids). Call a tool only if
  something critical for THIS business is still missing.
- Keep the report brief: at most 3 findings, one-sentence details and rationales, at most 3 missing_information items."""


def system_prompt(agent: str, role: str, ctx: RunContext, metrics: list[dict], budget: int) -> str:
    return (
        f"You are the {AGENT_LABELS[agent]} on a commercial-property investigation team.\n"
        f"{role}\n\n"
        f"USER'S ORIGINAL REQUEST (keep it central to every judgment): \"{ctx.query}\"\n"
        f"Business: {ctx.business['label']}. Space need: ~{ctx.target_sqft:,} sq ft ({ctx.target_basis}).\n"
        + (f"Extra requirements from the user: {ctx.extra_requirements}\n" if ctx.extra_requirements and ctx.extra_requirements not in ctx.query else "")
        + (f"Requirements mentioned: {', '.join(ctx.intent.get('requirements') or [])}\n" if ctx.intent.get("requirements") else "")
        + f"\nYOUR METRICS (assess every one):\n{metrics_brief(metrics)}\n\n"
        + COMMON_RULES.format(budget=budget)
        + (QUICK_RULES if ctx.mode == "quick" else "")
    )


async def _extract_output(transcript: str, metrics: list[dict], evidence: list[Evidence]) -> AgentOutput:
    """Constrained-JSON fallback: turn an agent's notes + evidence into a valid AgentOutput."""
    ev = "\n".join(f"{e.id} [{e.tool}]: {e.summary}" for e in evidence) or "(no evidence collected)"
    prompt = (
        "Convert this investigation into the required JSON report. Use ONLY the evidence listed; cite its ids. "
        f"Give exactly one metric assessment for each of these metric ids: {', '.join(m['id'] for m in metrics)}. "
        "Use status 'unknown' where the evidence does not settle a metric. Include 2-5 findings (what matters most "
        "for the user's business, each with why_it_matters and evidence ids) and list what the data cannot answer.\n\n"
        f"EVIDENCE:\n{ev}\n\nINVESTIGATION NOTES:\n{transcript[-6000:]}"
    )
    llm = chat_model().with_structured_output(AgentOutput, method="json_schema")
    return await asyncio.wait_for(llm.ainvoke(prompt), timeout=120)


def _parse_text_report(messages: list) -> AgentOutput | None:
    """Models sometimes write the final report as JSON text instead of the report tool; accept it if it validates."""
    for m in reversed(messages):
        if isinstance(m, AIMessage) and isinstance(m.content, str) and "{" in m.content:
            text = m.content.strip()
            if "```" in text:
                text = text.split("```")[1].removeprefix("json").strip()
            start, end = text.find("{"), text.rfind("}")
            try:
                return AgentOutput.model_validate_json(text[start : end + 1])
            except Exception:  # noqa: BLE001
                return None
    return None


def _transcript(messages: list) -> str:
    parts = []
    for m in messages:
        if isinstance(m, AIMessage):
            if m.content:
                parts.append(f"AGENT: {m.content if isinstance(m.content, str) else json.dumps(m.content)}")
            for tc in m.tool_calls or []:
                parts.append(f"CALL {tc['name']}({json.dumps(tc['args'])[:300]})")
        elif isinstance(m, ToolMessage):
            parts.append(f"RESULT: {str(m.content)[:800]}")
    return "\n".join(parts)


def prefetch(tools: list[StructuredTool], calls: list[tuple[str, dict]]) -> str:
    """Quick mode: run the given tool calls up front (they still register evidence and emit events) and
    return a block summarizing the results for the agent's first prompt."""
    by_name = {t.name: t for t in tools}
    lines = []
    for name, args in calls:
        if name not in by_name:
            continue
        try:
            out = json.loads(by_name[name].invoke(args))
        except Exception as err:  # noqa: BLE001 - a failed prefetch just isn't included
            log.warning("prefetch %s failed: %s", name, err)
            continue
        if out.get("evidence_id"):
            lines.append(f"{out['evidence_id']} [{name}]: {out.get('summary', '')}")
    return "PRE-GATHERED EVIDENCE (cite these ids):\n" + "\n".join(lines) if lines else ""


async def run_agent(
    ctx: RunContext, agent: str, role: str, task: str, tools: list[StructuredTool], budget: ToolBudget,
    prefetch_calls: list[tuple[str, dict]] | None = None, extra_tool_calls: int = 2, max_model_calls: int | None = None,
) -> AgentReport:
    """Run one Deep Agent investigation and return a validated AgentReport (never raises).

    With `prefetch_calls` (Quick mode) those tools run first and their results go into the task, the tool
    budget becomes what was used plus `extra_tool_calls`, and `max_model_calls` caps the agent's LLM calls."""
    start = time.time()
    metrics = ctx.metrics_for(agent)
    ctx.emit(agent, "start", f"{AGENT_LABELS[agent]} started — {len(metrics)} metrics to assess", {"metrics": [m["id"] for m in metrics]})
    if prefetch_calls:
        block = await asyncio.to_thread(prefetch, tools, prefetch_calls)
        budget.limit = budget.used + extra_tool_calls
        ready = ctx.shared.get(f"prefetched:{agent}")
        if isinstance(ready, asyncio.Event):
            ready.set()  # dependents (Cost) can start from this evidence without waiting for the write-up
        if block:
            task = f"{task}\n\n{block}"
    output: AgentOutput | None = None
    messages: list = []
    error: str | None = None
    try:
        graph = create_deep_agent(
            model=chat_model(),
            tools=tools,
            system_prompt=system_prompt(agent, role, ctx, metrics, budget.limit - budget.used),
            response_format=ToolStrategy(AgentOutput),
            middleware=[ModelCallLimitMiddleware(run_limit=max_model_calls or settings.agent_max_model_calls, exit_behavior="end")],
            name=f"{agent}_agent",
        )

        async def drive() -> dict:
            state: dict = {}
            seen: set[int] = set()
            async for chunk in graph.astream({"messages": [{"role": "user", "content": task}]}, {"recursion_limit": 4 * settings.agent_max_model_calls + 10}, stream_mode="values"):
                state = chunk
                msgs = chunk.get("messages") or []
                last = msgs[-1] if msgs else None
                if isinstance(last, AIMessage) and id(last) not in seen and isinstance(last.content, str) and last.content.strip() and not last.tool_calls:
                    seen.add(id(last))
                    text = last.content.strip()
                    if not text.startswith(("{", "```")):  # skip raw JSON reports
                        ctx.emit(agent, "thinking", text[:240], None)
            return state

        state = await asyncio.wait_for(drive(), timeout=settings.agent_timeout_s)
        messages = state.get("messages", [])
        output = state.get("structured_response")
    except AllProvidersFailedError:
        raise  # every provider is out: no point continuing
    except asyncio.TimeoutError:
        error = f"Timed out after {settings.agent_timeout_s:.0f}s"
    except Exception as err:  # noqa: BLE001 - one agent failing must not sink the analysis
        log.exception("%s agent crashed", agent)
        error = f"{type(err).__name__}: {err}"

    status = "completed"
    if output is None and messages:
        output = _parse_text_report(messages)
        if output is not None:
            ctx.emit(agent, "validation", "Report returned as JSON text instead of the report tool; parsed and validated it against the schema", None)
    if output is None:
        evidence = ctx.evidence.by_agent(agent)
        if evidence or messages:
            ctx.emit(agent, "validation", "No structured report returned; extracting one from the investigation (constrained JSON)", None)
            try:
                output = await _extract_output(_transcript(messages), metrics, evidence)
                status = "partial" if error else "completed"
            except AllProvidersFailedError:
                raise
            except Exception as err:  # noqa: BLE001
                error = error or f"Report extraction failed: {err}"
        if output is None:
            ctx.emit(agent, "error", error or "Agent produced no report", None)
            return AgentReport(agent=agent, label=AGENT_LABELS[agent], status="failed", summary="", tool_calls=budget.used, duration_s=round(time.time() - start, 1), error=error or "No report")

    report = to_report(ctx, agent, output, status, budget.used, time.time() - start, error)
    ctx.emit(agent, "done", f"Done in {report.duration_s:.0f}s · {report.tool_calls} tool calls · {len(report.findings)} findings", None)
    return report


def to_report(ctx: RunContext, agent: str, out: AgentOutput, status: str, tool_calls: int, duration: float, error: str | None) -> AgentReport:
    """Validate citations: findings citing nonexistent evidence are flagged unverified; unknown metric ids dropped."""
    valid = ctx.evidence.ids()
    allowed_metrics = {m["id"] for m in ctx.metrics_for(agent)}
    findings = []
    for i, f in enumerate(out.findings):
        cited = [e for e in f.evidence_ids if e in valid]
        findings.append(Finding(**{**f.model_dump(), "evidence_ids": cited}, id=f"{agent[:3]}-{i + 1}", verified=bool(cited) or f.kind == "assumption"))
    assessments: list[AgentMetricAssessment] = []
    for a in out.metric_assessments:
        if a.metric_id in allowed_metrics and a.metric_id not in {x.metric_id for x in assessments}:
            assessments.append(a.model_copy(update={"evidence_ids": [e for e in a.evidence_ids if e in valid]}))
    if not findings:
        # Keep outputs consistent: derive findings from evidenced metric assessments when the model gave none.
        names = {m["id"]: m["name"] for m in ctx.metrics_for(agent)}
        impact = {"strong": "positive", "adequate": "neutral", "weak": "negative", "blocker": "negative"}
        for a in assessments:
            if a.status == "unknown" or not a.evidence_ids:
                continue
            findings.append(Finding(
                id=f"{agent[:3]}-{len(findings) + 1}", title=f"{names.get(a.metric_id, a.metric_id)}: {a.status}", detail=a.rationale,
                impact=impact[a.status], severity="high" if a.status in {"weak", "blocker"} else "low", kind="inference",
                why_it_matters=next((m["why"] for m in ctx.metrics_for(agent) if m["id"] == a.metric_id), ""),
                evidence_ids=a.evidence_ids, metric_ids=[a.metric_id], verified=True,
            ))
    return AgentReport(
        agent=agent,
        label=AGENT_LABELS[agent],
        status=status,
        summary=out.summary,
        findings=findings,
        missing_information=out.missing_information,
        contradictions=out.contradictions,
        followups=out.followups,
        tool_calls=tool_calls,
        duration_s=round(duration, 1),
        error=error,
        metric_assessments=assessments,
    )


def deterministic_report(ctx: RunContext, agent: str, summary: str, assessments: list[AgentMetricAssessment], findings: list[AgentFinding], missing: list[str], status: str = "skipped") -> AgentReport:
    """Report for agents that cannot run (e.g., Matterport without data) — built without an LLM."""
    out = AgentOutput(summary=summary, metric_assessments=assessments, findings=findings, missing_information=missing)
    return to_report(ctx, agent, out, status, 0, 0, None)
