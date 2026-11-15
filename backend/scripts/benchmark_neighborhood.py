"""Before/after benchmark for the Neighborhood agent.

Runs ONLY the Neighborhood agent on fixed benchmark buildings (tests/benchmarks/neighborhood_cases.yaml) and
records, per case: each metric's status and evidence, tools used, unknown metrics, findings, time, LLM calls
and the headline numbers (workers, residents, competitors, walking reach). Point --backend at any checkout to
benchmark that version of the code, then compare two result files.

  # new code (this checkout)
  .venv/bin/python scripts/benchmark_neighborhood.py run --out /tmp/after.json
  # baseline: another checkout of the backend (e.g. the quick-mode branch)
  .venv/bin/python scripts/benchmark_neighborhood.py run --backend ../../other/newproj/backend --out /tmp/before.json
  # side-by-side report
  .venv/bin/python scripts/benchmark_neighborhood.py compare /tmp/before.json /tmp/after.json

Options: --only NAME[,NAME] to run a subset, --env FILE for API keys, --mode deep|quick (default deep: the agent chooses its tools).
Each case makes a few LLM calls through the normal provider chain (Codex -> Claude Code -> Ollama).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CASES = HERE.parent / "tests" / "benchmarks" / "neighborhood_cases.yaml"
HEADLINE_TOOLS = ("get_daytime_workers", "get_residents", "find_direct_competitors", "get_walkable_reach", "count_places", "get_demographics")


class _Log:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.start = time.time()

    def emit(self, agent: str, type_: str, message: str, data: dict | None = None) -> None:
        self.events.append({"t": round(time.time() - self.start, 1), "agent": agent, "type": type_, "message": message[:300]})


async def run_case(case: dict, mode: str) -> dict:
    import db  # noqa: F401  (imported from the selected backend)
    import multi_agent_engine as engine
    from agents import neighborhood_agent
    from config import business
    from schemas import AnalysisRequest
    from services import intent as intent_svc
    from services import llm, vexcel
    from services.geo import haversine_m

    intent = await intent_svc.parse(case["query"])
    feats = await vexcel.property_extract(case["lat"], case["lon"], 120, limit=8, calculated=True)
    if not feats:
        return {"name": case["name"], "error": "no Vexcel building at this point"}
    cands = [(vexcel.summarize_feature(f), f) for f in feats]
    prop, feature = min(cands, key=lambda cf: haversine_m(case["lat"], case["lon"], cf[0]["lat"], cf[0]["lon"]))
    radius = business(intent.business_type)["default_radius_m"]
    req = AnalysisRequest(query=case["query"], intent=intent, property_id=prop["id"], radius_m=radius, requirements=case.get("extra"), mode=mode)
    if req.requirements and hasattr(intent_svc, "refine"):
        refined = await intent_svc.refine(req.intent, req.query, req.requirements)
        req = req.model_copy(update={"intent": refined, "query": intent_svc.combine_request(req.query, req.requirements)})
    log = _Log()
    ctx = await engine.build_context(req, prop, feature, log)
    if hasattr(ctx, "mode"):
        ctx.mode = mode
    usage = llm.track_usage() if hasattr(llm, "track_usage") else {}
    t0 = time.time()
    rep = await neighborhood_agent.run(ctx)
    duration = time.time() - t0

    evidence = [e for e in ctx.evidence.all() if e.agent == "neighborhood"]
    headline = {}
    for e in evidence:
        if e.tool in HEADLINE_TOOLS and e.tool not in headline:
            headline[e.tool] = e.summary[:220]
    metrics = {a.metric_id: {"status": a.status, "evidence": len(a.evidence_ids), "rationale": a.rationale[:240]} for a in rep.metric_assessments}
    expect = case.get("expect") or {}
    checks = {m: (metrics.get(m, {}).get("status") in ok) for m, ok in expect.items()}
    return {
        "name": case["name"], "query": case["query"], "address": ctx.property.get("address"), "business": intent.business_type,
        "status": rep.status, "error": rep.error, "duration_s": round(duration, 1), "tool_calls": rep.tool_calls,
        "tools_used": sorted({e.tool for e in evidence}), "evidence": len(evidence),
        "metrics": metrics, "unknown_metrics": sum(1 for m in metrics.values() if m["status"] == "unknown"),
        "cited_metrics": sum(1 for m in metrics.values() if m["evidence"] > 0),
        "findings": len(rep.findings), "missing_information": len(rep.missing_information),
        "headline": headline, "llm_calls": dict(usage), "expect": expect, "expect_met": checks,
        "summary": rep.summary[:400],
        "events": [e for e in log.events if e["agent"] == "neighborhood"],
    }


async def run_all(args: argparse.Namespace) -> list[dict]:
    import yaml

    cases = yaml.safe_load(Path(args.cases).read_text())
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["name"] in wanted]
    out = []
    for c in cases:
        print(f"> {c['name']} ...", flush=True)
        try:
            res = await run_case(c, args.mode)
        except Exception as err:  # noqa: BLE001 - one bad case shouldn't stop the run
            res = {"name": c["name"], "error": f"{type(err).__name__}: {err}"}
        out.append(res)
        print(f"  {res.get('status', 'error')} in {res.get('duration_s', '-')}s, tools {res.get('tools_used')}, unknown {res.get('unknown_metrics')}", flush=True)
    return out


def compare(before: list[dict], after: list[dict]) -> str:
    b, a = {r["name"]: r for r in before}, {r["name"]: r for r in after}
    lines = ["# Neighborhood agent: before vs after", ""]
    lines += ["| Case | Time (s) | Tool calls | Evidence | Unknown metrics | Cited metrics | Expectation met |", "|---|---|---|---|---|---|---|"]
    for name in b.keys() | a.keys():
        x, y = b.get(name, {}), a.get(name, {})
        exp = lambda r: ", ".join(f"{k}:{'yes' if v else 'no'}" for k, v in (r.get("expect_met") or {}).items()) or "-"
        lines.append(f"| {name} | {x.get('duration_s', '-')} → {y.get('duration_s', '-')} | {x.get('tool_calls', '-')} → {y.get('tool_calls', '-')} | "
                     f"{x.get('evidence', '-')} → {y.get('evidence', '-')} | {x.get('unknown_metrics', '-')} → {y.get('unknown_metrics', '-')} | "
                     f"{x.get('cited_metrics', '-')} → {y.get('cited_metrics', '-')} | {exp(x)} → {exp(y)} |")
    for name in sorted(b.keys() | a.keys()):
        x, y = b.get(name, {}), a.get(name, {})
        lines += ["", f"## {name}", f"_{y.get('query') or x.get('query')}_ — {y.get('address') or x.get('address') or ''}", ""]
        lines += ["| Metric | Before | After |", "|---|---|---|"]
        for m in sorted((x.get("metrics") or {}).keys() | (y.get("metrics") or {}).keys()):
            fx, fy = (x.get("metrics") or {}).get(m, {}), (y.get("metrics") or {}).get(m, {})
            lines.append(f"| {m} | {fx.get('status', '-')} ({fx.get('evidence', 0)} ev) | {fy.get('status', '-')} ({fy.get('evidence', 0)} ev) |")
        lines += ["", f"- Tools before: {', '.join(x.get('tools_used') or []) or '-'}", f"- Tools after: {', '.join(y.get('tools_used') or []) or '-'}"]
        for tool, text in (y.get("headline") or {}).items():
            if tool not in (x.get("headline") or {}):
                lines.append(f"- New signal `{tool}`: {text}")
        for label, r in (("before", x), ("after", y)):
            if r.get("error"):
                lines.append(f"- Error {label}: {r['error']}")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--backend", default=str(HERE.parent), help="backend directory whose code to benchmark")
    r.add_argument("--cases", default=str(DEFAULT_CASES))
    r.add_argument("--only", default="", help="comma-separated case names")
    r.add_argument("--mode", default="deep", choices=["deep", "quick"])
    r.add_argument("--out", required=True)
    r.add_argument("--env", default="", help=".env to load first (default: <backend>/.env)")
    c = sub.add_parser("compare")
    c.add_argument("before")
    c.add_argument("after")
    c.add_argument("--md", default="", help="also write the report to this markdown file")
    args = p.parse_args()

    if args.cmd == "compare":
        report = compare(json.loads(Path(args.before).read_text()), json.loads(Path(args.after).read_text()))
        print(report)
        if args.md:
            Path(args.md).write_text(report)
        return

    backend = Path(args.backend).resolve()
    os.environ.setdefault("DATABASE_PATH", str(Path(tempfile.gettempdir()) / "turnkey-benchmark.db"))  # never touches the app's DB
    env_file = Path(args.env).resolve() if args.env else backend / ".env"
    if env_file.exists():  # keys (Vexcel etc.) must be in the environment before config is imported
        from dotenv import load_dotenv
        load_dotenv(env_file)
    sys.path.insert(0, str(backend))
    os.chdir(backend)
    results = asyncio.run(run_all(args))
    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
