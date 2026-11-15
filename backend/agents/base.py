"""Shared agent harness: LangChain Deep Agents on the LLM fallback chain (Codex → Claude Code → Ollama), evidence tracking, bounded tool use,
structured output with a constrained-JSON fallback, and live progress events.

Every tool result is registered as evidence with an id (E1, E2...). Agents must cite those ids; a
citation only counts when the citing agent actually saw that evidence (its own tool results, or ids
the engine shared with it), and a non-unknown metric status only counts evidence that carries data.
Tools refuse repeated identical calls and stop working once the agent's budget is spent, so
investigations stay purposeful. A timed-out or misbehaving agent keeps what it gathered: its report is
rescued from the partial conversation and marked "partial".
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
from schemas import AgentFinding, AgentMetricAssessment, AgentOutput, AgentReport, Evidence, Finding, NeedCheck
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
        with self._lock:
            return {e.id for e in self._items}

    def get(self, eid: str) -> Evidence | None:
        with self._lock:
            return next((e for e in self._items if e.id == eid), None)

    def by_agent(self, agent: str) -> list[Evidence]:
        with self._lock:
            return [e for e in self._items if e.agent == agent]

    def all(self) -> list[Evidence]:
        with self._lock:
            return list(self._items)

    def find(self, tool: str, data: Any) -> str | None:
        """Id of an existing item from `tool` with exactly this data (lets the engine reuse an agent's identical result)."""
        with self._lock:
            return next((e.id for e in reversed(self._items) if e.tool == tool and e.data == data), None)


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
    program: dict = field(default_factory=dict)  # services/program.py: what the user's request implies
    deadline: float | None = None  # epoch seconds by which the whole analysis must finish
    building: dict = field(default_factory=dict)  # services/building_facts.py output for the selected property
    mode: str = "deep"  # "quick" = pre-gathered evidence, fewer model calls, brief reports; "deep" = full investigation

    def time_left(self, cap: float) -> float:
        """Seconds an operation may take: `cap`, shortened to fit the analysis deadline (never below 20 s)."""
        if self.deadline is None:
            return cap
        return max(20.0, min(cap, self.deadline - time.time()))

    def visible_evidence(self, agent: str) -> set[str]:
        """Evidence ids `agent` may cite: its own tool results, the engine's verified context, and ids the
        engine explicitly shared with it (e.g. upstream findings handed to the Cost Agent)."""
        own = {e.id for e in self.evidence.all() if e.agent in (agent, "engine")}
        return own | set(self.shared.get(f"visible:{agent}", ()))

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
    def __init__(self, limit: int, seen: dict[str, str] | None = None) -> None:
        self.limit = min(limit, settings.agent_max_tool_calls)
        self.used = 0
        # call key -> evidence id ("" while running). Pass the same dict to a follow-up so it reuses earlier results.
        self.seen: dict[str, str] = seen if seen is not None else {}
        self.lock = threading.Lock()  # tools may run in parallel threads within one model turn

    def reserve(self, key: str) -> str | None:
        """Atomically claim a budget slot for this call. Returns a refusal note, or None when the call may run."""
        with self.lock:
            if key in self.seen:
                eid = self.seen[key]
                return f"Already called with these arguments; see evidence {eid}. Use that result." if eid else "The same call is already running; wait for its result instead of repeating it."
            if self.used >= self.limit:
                return "Tool budget exhausted. Stop investigating and return your structured report now."
            self.used += 1
            self.seen[key] = ""
            return None


MAX_TOOL_PAYLOAD_CHARS = 6000


def _compact(value: Any, depth: int = 0) -> Any:
    """Drop empty/false/null fields and long tails so tool output stays readable (full data stays in evidence)."""
    if isinstance(value, dict):
        out = {k: _compact(v, depth + 1) for k, v in value.items() if v not in (None, False, "", [], {})}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        items = [_compact(v, depth + 1) for v in value[:25]]
        return items + ([f"... {len(value) - 25} more"] if len(value) > 25 else [])
    return value


def _payload_json(payload: dict) -> str:
    text = json.dumps(payload, default=str)
    if len(text) <= MAX_TOOL_PAYLOAD_CHARS or "data" not in payload:
        return text
    slim = {**payload, "data": _compact(payload["data"])}
    text = json.dumps(slim, default=str)
    if len(text) <= MAX_TOOL_PAYLOAD_CHARS:
        return text
    slim["data"] = json.dumps(slim["data"], default=str)[: MAX_TOOL_PAYLOAD_CHARS - 400] + " …(truncated; full data kept in the evidence record)"
    return json.dumps(slim, default=str)


def tracked_tool(ctx: RunContext, agent: str, budget: ToolBudget, source: str) -> Callable[[Callable[..., dict]], StructuredTool]:
    """Decorator: turns a function returning {summary, data, url?} into a LangChain tool that registers
    evidence, emits events, refuses duplicate calls and enforces the budget."""

    def wrap(fn: Callable[..., dict]) -> StructuredTool:
        @functools.wraps(fn)
        def runner(**kwargs: Any) -> str:
            key = f"{fn.__name__}:{json.dumps(kwargs, sort_keys=True, default=lambda o: o.model_dump() if hasattr(o, 'model_dump') else str(o))}"
            refusal = budget.reserve(key)
            if refusal:
                return json.dumps({"note": refusal})
            safe_args = json.loads(json.dumps(kwargs, default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o)))
            shown = ", ".join(f"{k}={json.dumps(v) if isinstance(v, (list, dict)) else v}" for k, v in safe_args.items())
            ctx.emit(agent, "tool_call", f"{fn.__name__}({shown[:200]})", {"tool": fn.__name__, "args": safe_args})
            try:
                result = fn(**kwargs)
            except Exception as err:  # noqa: BLE001 - surface tool errors to the agent as data
                log.exception("tool %s failed", fn.__name__)
                with budget.lock:
                    budget.seen.pop(key, None)  # a failed call may be retried
                ctx.emit(agent, "error", f"{fn.__name__} failed: {err}", None)
                return json.dumps({"error": str(err)})
            eid = ctx.evidence.add(agent, fn.__name__, result.get("source", source), result["summary"], result.get("data"), result.get("url"))
            with budget.lock:
                budget.seen[key] = eid
            ctx.emit(agent, "tool_result", f"{eid}: {result['summary']}", {"evidence_id": eid, "tool": fn.__name__, "args": safe_args})
            payload = {"evidence_id": eid, "summary": result["summary"], **({"data": result["data"]} if result.get("data") is not None else {})}
            if result.get("guidance"):
                payload["interpretation_notes"] = result["guidance"]
            return _payload_json(payload)

        runner.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
        return StructuredTool.from_function(func=runner, name=fn.__name__, description=inspect.getdoc(fn) or fn.__name__)

    return wrap


BUILDING_FACT_GROUPS = {
    "building": ["year_built", "last_renovation_year", "renovated_systems", "building_class", "condition_rating", "property_subtype", "construction_material", "stories", "building_height_ft", "ceiling_height_ft", "elevators", "gross_sqft", "typical_floor_sqft"],
    "site": ["parking_spaces", "parking_ratio_per_1000", "zoning_code", "sprinklers", "footprint_sqft", "paved_area_sqft"],
    "space": ["available_sqft", "second_generation_use", "prior_buildout_status", "cam_per_sqft_yr"],
}


def building_facts_result(ctx: RunContext, group: str) -> dict:
    """Tool result for get_building_facts: recorded facts (with source and confidence) for one group."""
    table = (ctx.building or {}).get("facts") or {}
    ids = BUILDING_FACT_GROUPS.get(group) or [i for g in BUILDING_FACT_GROUPS.values() for i in g]
    rows = {i: table[i] for i in ids if i in table}
    if not rows:
        return {"summary": f"No recorded {group} facts for this building (no CoStar match)", "data": None, "source": "CoStar building record"}
    shown = ", ".join(f"{i.replace('_', ' ')} {r['value']}{(' ' + r['unit']) if r.get('unit') else ''} ({r['source']})" for i, r in list(rows.items())[:8])
    return {
        "summary": f"{len(rows)} recorded {group} facts: {shown}",
        "data": rows,
        "source": "CoStar building record" + (" + Vexcel" if any(r["source"] != "CoStar" for r in rows.values()) else ""),
        "guidance": ["CoStar values are recorded by researchers (high/medium confidence); Vexcel/estimated values are inferred. A missing fact is unknown, not absent."],
    }


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
8. Explain why each finding matters for the user's specific business and stated needs, not in general.
9. Finish by returning your structured report (AgentOutput) with one metric assessment per assigned metric id, and one `needs` entry per need listed under NEEDS YOU MUST CHECK (met / unmet only with evidence, otherwise unknown)."""


def program_brief(ctx: RunContext, agent: str) -> str:
    """The user's space program, plus the stated needs this agent is responsible for checking."""
    p = ctx.program
    if not p:
        return ""
    occ = p["occupancy"]
    lines = ["USER'S SPACE PROGRAM (derived from their request; respect it in every judgment):"]
    if occ["counts"]:
        lines.append("- Stated: " + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in occ["counts"].items()))
    lines.append(f"- Size: ~{p['size']['target_sqft']:,} sq ft (acceptable {p['size']['min_sqft']:,}-{p['size']['max_sqft']:,}); {p['size']['basis'][0] if p['size']['basis'] else ''}")
    lines.append(f"- Occupancy: ~{occ['occupant_load']} occupants, IBC Group {occ['group']}. " + "; ".join(f"{c['rule']}: {c['value']}" for c in p["code"] if c["id"] in {"exits", "restrooms", "sprinklers"}))
    b = p["building"]
    lines.append(f"- Building: ground floor {b['ground_floor']}; ceiling {b['min_ceiling_ft']}+ ft ({b['ceiling_reason']})")
    if p.get("timeline"):
        lines.append(f"- Timeline: {p['timeline']['detail']}")
    if p.get("tenure") == "buy":
        lines.append("- The user wants to BUY, not lease.")
    if p.get("near"):
        lines.append(f"- Wants to be near: {', '.join(p['near'])}")
    if p.get("avoid"):
        lines.append(f"- Wants to avoid: {', '.join(p['avoid'])}")
    mine = [n for n in p["needs"] if n["owner"] == agent]
    others = [n for n in p["needs"] if n["owner"] != agent]
    if mine:
        lines.append("NEEDS YOU MUST CHECK (report each one in `needs` by its id, and in a finding when it matters; must-haves first):")
        lines += [f"- [{n['priority'].upper()}] {n['label']} (id: {n['id']}): {n['triggers']}" for n in sorted(mine, key=lambda n: n["priority"] != "must")]
    if others:
        lines.append("Other stated needs (checked by teammates): " + ", ".join(f"{n['label']} ({n['priority']})" for n in others))
    return "\n".join(lines) + "\n\n"


QUICK_RULES = """
QUICK MODE (the user asked for a fast answer):
- The key evidence for your metrics is already gathered below the request (cite its E-ids). Call a tool only if
  something critical for THIS business, or a need you must check, is still missing evidence.
- Keep the report brief: at most 3 findings, one-sentence details and rationales, at most 3 missing_information
  items. Still report every need you must check in `needs`."""


def requirements_brief(ctx: RunContext) -> str:
    """Fallback when no space program was built: the user's stated needs and budgets as primary goals."""
    needs = [r for r in ctx.intent.get("requirements") or [] if r.strip()]
    budgets = [f"${b['amount']:,.0f} {b['period']}" for b in ctx.intent.get("budgets") or [] if b.get("amount")]
    if not needs and not budgets:
        return ""
    lines = [f"- {n}" for n in needs] + [f"- budget: {b}" for b in budgets]
    return (
        "\nTHE USER'S STATED REQUIREMENTS (primary goals; each one is checked and an unmet one caps the verdict):\n"
        + "\n".join(lines)
        + "\nFor every requirement your tools can speak to, gather evidence and add a finding titled "
        "'Requirement: <requirement>' that says met / not met / unclear, citing evidence ids. Skip ones outside your domain.\n"
    )


def system_prompt(agent: str, role: str, ctx: RunContext, metrics: list[dict], budget: int) -> str:
    return (
        f"You are the {AGENT_LABELS[agent]} on a commercial-property investigation team.\n"
        f"{role}\n\n"
        f"USER'S ORIGINAL REQUEST (keep it central to every judgment): \"{ctx.query}\"\n"
        f"Business: {ctx.business['label']}. Space need: ~{ctx.target_sqft:,} sq ft ({ctx.target_basis}).\n"
        + (f"Extra requirements from the user: {ctx.extra_requirements}\n" if ctx.extra_requirements and ctx.extra_requirements not in ctx.query else "")
        + (f"Requirements mentioned: {', '.join(ctx.intent.get('requirements') or [])}\n" if ctx.intent.get("requirements") and not ctx.program else "")
        + "\n" + (program_brief(ctx, agent) or requirements_brief(ctx))
        + f"YOUR METRICS (assess every one):\n{metrics_brief(metrics)}\n\n"
        + COMMON_RULES.format(budget=budget)
        + (QUICK_RULES if ctx.mode == "quick" else "")
    )


async def _extract_output(ctx: RunContext, agent: str, transcript: str, metrics: list[dict], evidence: list[Evidence], model: Any = None) -> AgentOutput:
    """Constrained-JSON fallback: turn an agent's notes + evidence into a valid AgentOutput.

    Gets the same metric definitions and status guides the agent had, so a rescued report is judged by the
    same rules as a normal one."""
    ev = "\n".join(f"{e.id} [{e.tool}]: {e.summary}" for e in evidence) or "(no evidence collected)"
    needs = [n for n in (ctx.program or {}).get("needs", []) if n.get("owner") == agent]
    prompt = (
        f"You are finishing the {AGENT_LABELS[agent]}'s report for a {ctx.business['label'].lower()}. "
        f"User's request: \"{ctx.query}\".\n"
        "Convert this investigation into the required JSON report. Use ONLY the evidence listed; cite its ids. "
        f"Give exactly one metric assessment for each of these metrics, choosing statuses with their status guides:\n{metrics_brief(metrics)}\n"
        "Use status 'unknown' where the evidence does not settle a metric. Include 2-5 findings (what matters most "
        "for the user's business, each with why_it_matters and evidence ids) and list what the data cannot answer.\n"
        + (f"Report each of these needs in `needs` (met/unmet only with evidence): {', '.join(n['id'] for n in needs)}.\n" if needs else "")
        + f"\nEVIDENCE:\n{ev}\n\nINVESTIGATION NOTES:\n{transcript[-6000:] or '(the investigation was cut off before writing notes)'}"
    )
    llm = (model or chat_model()).with_structured_output(AgentOutput, method="json_schema")
    return await asyncio.wait_for(llm.ainvoke(prompt), timeout=ctx.time_left(120))


def _parse_text_report(messages: list) -> AgentOutput | None:
    """Models sometimes write the final report as JSON text instead of the report tool; accept the latest one that validates."""
    for m in reversed(messages):
        if isinstance(m, AIMessage) and isinstance(m.content, str) and "{" in m.content:
            text = m.content.strip()
            if "```" in text:
                text = text.split("```")[1].removeprefix("json").strip()
            start, end = text.find("{"), text.rfind("}")
            try:
                return AgentOutput.model_validate_json(text[start : end + 1])
            except Exception:  # noqa: BLE001 - try earlier messages
                continue
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
    model: Any = None, metric_ids: list[str] | None = None,
    prefetch_calls: list[tuple[str, dict]] | None = None, extra_tool_calls: int = 2, max_model_calls: int | None = None,
) -> AgentReport:
    """Run one Deep Agent investigation and return a validated AgentReport.

    Never raises, except AllProvidersFailedError with `exhausted=True` (every LLM provider is out, so the
    whole analysis should stop). `model` replaces the LLM (tests use a scripted fake); `metric_ids` narrows a
    follow-up to the metrics it is about. With `prefetch_calls` (Quick mode) those tools run first and their
    results go into the task, the tool budget becomes what was used plus `extra_tool_calls`, and
    `max_model_calls` caps the agent's LLM calls."""
    start = time.time()
    metrics = [m for m in ctx.metrics_for(agent) if metric_ids is None or m["id"] in metric_ids]
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
    latest: dict = {}  # the newest streamed graph state: survives a timeout so partial work is kept
    error: str | None = None
    llm = model or chat_model()
    timeout = ctx.time_left(settings.agent_timeout_s)
    try:
        graph = create_deep_agent(
            model=llm,
            tools=tools,
            system_prompt=system_prompt(agent, role, ctx, metrics, budget.limit - budget.used),
            response_format=ToolStrategy(AgentOutput),
            middleware=[ModelCallLimitMiddleware(run_limit=max_model_calls or settings.agent_max_model_calls, exit_behavior="end")],
            name=f"{agent}_agent",
        )

        async def drive() -> None:
            seen: set[int] = set()
            async for chunk in graph.astream({"messages": [{"role": "user", "content": task}]}, {"recursion_limit": 4 * settings.agent_max_model_calls + 10}, stream_mode="values"):
                latest.clear()
                latest.update(chunk)
                msgs = chunk.get("messages") or []
                last = msgs[-1] if msgs else None
                if isinstance(last, AIMessage) and id(last) not in seen and isinstance(last.content, str) and last.content.strip() and not last.tool_calls:
                    seen.add(id(last))
                    text = last.content.strip()
                    if not text.startswith(("{", "```")):  # skip raw JSON reports
                        ctx.emit(agent, "thinking", text[:240], None)

        await asyncio.wait_for(drive(), timeout=timeout)
        output = latest.get("structured_response")
    except AllProvidersFailedError as err:
        if err.exhausted:
            raise  # every provider is out: no point continuing the analysis
        log.warning("%s agent: every provider failed this call: %s", agent, err)
        error = f"LLM call failed on every provider: {err}"[:400]
    except asyncio.TimeoutError:
        error = f"Timed out after {timeout:.0f}s"
    except Exception as err:  # noqa: BLE001 - one agent failing must not sink the analysis
        log.exception("%s agent crashed", agent)
        error = f"{type(err).__name__}: {err}"
    messages: list = latest.get("messages", [])

    status = "completed" if error is None else "partial"
    if output is None and messages:
        output = _parse_text_report(messages)
        if output is not None:
            ctx.emit(agent, "validation", "Report returned as JSON text instead of the report tool; parsed and validated it against the schema", None)
    if output is None:
        evidence = ctx.evidence.by_agent(agent)
        if evidence or messages:
            ctx.emit(agent, "validation", "No structured report returned; extracting one from the investigation (constrained JSON)", None)
            try:
                output = await _extract_output(ctx, agent, _transcript(messages), metrics, evidence, model)
                status = "partial"  # rescued: judged from partial notes, not a finished investigation
            except AllProvidersFailedError as err:
                if err.exhausted:
                    raise
                error = error or f"Report extraction failed: {err}"
            except Exception as err:  # noqa: BLE001
                error = error or f"Report extraction failed: {err}"
        if output is None:
            ctx.emit(agent, "error", error or "Agent produced no report", None)
            return AgentReport(agent=agent, label=AGENT_LABELS[agent], status="failed", summary="", tool_calls=budget.used, duration_s=round(time.time() - start, 1), error=error or "No report")

    report = to_report(ctx, agent, output, status, budget.used, time.time() - start, error, metric_ids)
    ctx.emit(agent, "done", f"Done in {report.duration_s:.0f}s · {report.tool_calls} tool calls · {len(report.findings)} findings", None)
    return report


def to_report(ctx: RunContext, agent: str, out: AgentOutput, status: str, tool_calls: int, duration: float, error: str | None, metric_ids: list[str] | None = None) -> AgentReport:
    """Validate an agent's output into a complete report.

    - Citations count only when this agent saw the evidence (own tool results or ids shared with it):
      a hallucinated "E4" that happens to be another agent's evidence is dropped.
    - A non-unknown metric status only keeps evidence that carries data ("data unavailable" results
      don't support a conclusion).
    - Unknown/duplicate metric ids are dropped; every assigned metric and owned need gets an entry
      ('unknown' when the agent didn't report it)."""
    visible = ctx.visible_evidence(agent)

    def has_data(eid: str) -> bool:
        e = ctx.evidence.get(eid)
        return e is not None and e.data is not None

    assigned = [m for m in ctx.metrics_for(agent) if metric_ids is None or m["id"] in metric_ids]
    allowed_metrics = {m["id"] for m in assigned}
    findings = []
    for i, f in enumerate(out.findings):
        cited = [e for e in f.evidence_ids if e in visible]
        findings.append(Finding(**{**f.model_dump(), "evidence_ids": cited}, id=f"{agent[:3]}-{i + 1}", verified=bool(cited) or f.kind == "assumption"))
    assessments: list[AgentMetricAssessment] = []
    for a in out.metric_assessments:
        if a.metric_id in allowed_metrics and a.metric_id not in {x.metric_id for x in assessments}:
            cited = [e for e in a.evidence_ids if e in visible and (a.status == "unknown" or has_data(e))]
            assessments.append(a.model_copy(update={"evidence_ids": cited}))
    reason = "the agent failed before assessing it" if status == "failed" else "the agent did not assess it"
    assessments += [AgentMetricAssessment(metric_id=m["id"], status="unknown", rationale=f"Not assessed ({reason}).") for m in assigned if m["id"] not in {a.metric_id for a in assessments}]

    owned = [n for n in (ctx.program or {}).get("needs", []) if n.get("owner") == agent]
    owned_ids = {n["id"] for n in owned}
    needs: list[NeedCheck] = []
    for n in out.needs:
        if n.need_id in owned_ids and n.need_id not in {x.need_id for x in needs}:
            cited = [e for e in n.evidence_ids if e in visible and has_data(e)]
            needs.append(n.model_copy(update={"evidence_ids": cited, "status": n.status if cited or n.status == "unknown" else "unknown"}))
    needs += [NeedCheck(need_id=n["id"], status="unknown", detail=f"Not reported by the {AGENT_LABELS[agent]}; verify: {n['label'].lower()}.") for n in owned if n["id"] not in {x.need_id for x in needs}]
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
        needs=needs,
        metric_assessments=assessments,
    )


def deterministic_report(ctx: RunContext, agent: str, summary: str, assessments: list[AgentMetricAssessment], findings: list[AgentFinding], missing: list[str], status: str = "skipped") -> AgentReport:
    """Report for agents that cannot run (e.g., Matterport without data) — built without an LLM."""
    out = AgentOutput(summary=summary, metric_assessments=assessments, findings=findings, missing_information=missing)
    return to_report(ctx, agent, out, status, 0, 0, None)
