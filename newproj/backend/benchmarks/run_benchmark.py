"""Run the fixed agent benchmark and write a JSON report.

    cd backend && .venv/bin/python benchmarks/run_benchmark.py --label before
    .venv/bin/python benchmarks/run_benchmark.py --compare benchmarks/results/before.json benchmarks/results/after.json

Uses its own SQLite file (benchmarks/bench.db), so the app's data is untouched. Caches (OpenStreetMap places,
Census, reverse geocoding) are warmed before timing so slow public APIs don't distort the comparison.
Metrics are computed in Python from each result; no LLM judges the output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["DATABASE_PATH"] = str(HERE / "bench.db")

import yaml  # noqa: E402

import db  # noqa: E402
import multi_agent_engine  # noqa: E402
from config import business  # noqa: E402
from schemas import AnalysisRequest  # noqa: E402
from services import external, vexcel  # noqa: E402
from services.intent import parse_rules  # noqa: E402


async def load_property(lat: float, lon: float) -> dict:
    feats = await vexcel.property_extract(lat, lon, 80, limit=8, calculated=True)
    if not feats:
        raise RuntimeError(f"no Vexcel parcel near {lat},{lon}")
    summaries = [(vexcel.summarize_feature(f), f) for f in feats]
    commercial = [s for s in summaries if s[0].get("building_type") == "commercial" and not s[0].get("_too_low")]
    cand, raw = (commercial or summaries)[0]
    cand = {k: v for k, v in cand.items() if not k.startswith("_")} | {"match_score": 0, "match_reasons": []}
    db.save_property(cand, raw)
    return cand


def check(exp: dict, result: dict) -> bool:
    metrics = {m["id"]: m for m in result.get("metrics", [])}
    if "metric" in exp:
        status = metrics.get(exp["metric"], {}).get("status")
        return status in exp["in"] if "in" in exp else status not in exp["not_in"]
    if "evidence_tool" in exp:
        return any(e["tool"] == exp["evidence_tool"] for e in result.get("evidence", []))
    if "cost_flag" in exp:
        return any(e["tool"] == "estimate_costs" and isinstance(e.get("data"), dict) and e["data"].get(exp["cost_flag"]) for e in result.get("evidence", [])) \
            or bool((result.get("costs") or {}).get(exp["cost_flag"]))
    if "budget_status" in exp:
        checks = (result.get("costs") or {}).get("budgets") or [(result.get("costs") or {}).get("budget") or {}]
        return any(c.get("status") == exp["budget_status"] for c in checks)
    raise ValueError(f"unknown expectation {exp}")


def summarize(case: dict, analysis: dict) -> dict:
    r = analysis.get("result") or {}
    metrics = [m for m in r.get("metrics", []) if m.get("weight", 0) > 0]
    total_w = sum(m["weight"] for m in metrics) or 1
    llm_calls = {}
    for s in r.get("data_sources", []):
        if s["name"].startswith("LLM:"):
            n = int(re.match(r"(\d+)", s["note"]).group(1)) if re.match(r"(\d+)", s["note"] or "") else 0
            if n:
                llm_calls[s["name"][5:]] = n
    events = analysis.get("events", [])
    out = {
        "id": case["id"],
        "status": analysis["status"],
        "error": analysis.get("error"),
        "duration_s": events[-1]["t"] if events else None,
        "llm_calls": sum(llm_calls.values()),
        "llm_providers": llm_calls,
        "tool_calls": sum(a.get("tool_calls", 0) for a in r.get("agents", [])),
        "evidence_items": len(r.get("evidence", [])),
        "score": (r.get("recommendation") or {}).get("score"),
        "verdict": (r.get("recommendation") or {}).get("verdict"),
        "confidence": (r.get("recommendation") or {}).get("confidence"),
        "unknown_weight_pct": round(100 * sum(m["weight"] for m in metrics if m["status"] == "unknown") / total_w),
        "evidenced_weight_pct": round(100 * sum(m["weight"] for m in metrics if m.get("evidence_ids")) / total_w),
        "unverified_findings": sum(1 for a in r.get("agents", []) for f in a.get("findings", []) if not f.get("verified", True)),
        "statuses": {m["id"]: m["status"] for m in r.get("metrics", [])},
        "expect": {},
    }
    for tier in ("core", "upgrade"):
        res = [check(e, r) if r else False for e in case.get("expect", {}).get(tier, [])]
        out["expect"][tier] = {"passed": sum(res), "total": len(res), "detail": [{"exp": e, "ok": ok} for e, ok in zip(case["expect"].get(tier, []), res)]}
    return out


async def run(label: str, only: list[str] | None) -> Path:
    cases = yaml.safe_load((HERE / "cases.yaml").read_text())["cases"]
    if only:
        cases = [c for c in cases if c["id"] in only]
    db.conn()
    props = {}
    print("warming caches (not timed)...", flush=True)
    try:  # newer versions use Census LODES worker data: build its index before timing
        from services import lodes

        t = time.time()
        await asyncio.to_thread(lodes.index, "tx")
        print(f"  LODES index ready ({time.time() - t:.1f}s)", flush=True)
    except ImportError:
        pass
    for c in cases:
        props[c["id"]] = await load_property(c["lat"], c["lon"])
        p = props[c["id"]]
        for attempt in range(3):
            try:
                await external.nearby_places(p["lat"], p["lon"])
                break
            except Exception as err:  # noqa: BLE001
                print(f"  places retry {attempt + 1} for {c['id']}: {err}", flush=True)
                await asyncio.sleep(5)
        await external.census_profile(p["lat"], p["lon"])
        await external.reverse(p["lat"], p["lon"])
        print(f"  {c['id']}: {p['id']} {p.get('building_type')} {p.get('area_sqft')} sqft", flush=True)

    rows = []
    for c in cases:
        intent = parse_rules(c["query"])
        cfg = business(intent.business_type)
        req = AnalysisRequest(query=c["query"], intent=intent, property_id=props[c["id"]]["id"], radius_m=cfg["default_radius_m"],
                              requirements=c.get("extra"), mode=c.get("mode", "quick"))
        aid = f"bench-{label}-{c['id']}-{uuid.uuid4().hex[:4]}"
        db.create_analysis(aid, req.query, req.intent.model_dump(), props[c["id"]], req.radius_m, req.mode, None, req.requirements)
        t = time.time()
        await multi_agent_engine.run_analysis(aid, req)
        row = summarize(c, db.get_analysis(aid))
        row["wall_s"] = round(time.time() - t, 1)
        rows.append(row)
        print(f"  {c['id']:30} {row['status']:9} {row['duration_s']}s llm={row['llm_calls']} tools={row['tool_calls']} "
              f"unknown={row['unknown_weight_pct']}% conf={row['confidence']} core={row['expect']['core']['passed']}/{row['expect']['core']['total']} "
              f"upgrade={row['expect']['upgrade']['passed']}/{row['expect']['upgrade']['total']}", flush=True)

    out = HERE / "results" / f"{label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"label": label, "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": rows}, indent=2))
    print(f"wrote {out}")
    return out


def compare(a_path: str, b_path: str) -> None:
    a, b = json.loads(Path(a_path).read_text()), json.loads(Path(b_path).read_text())
    keys = ["duration_s", "llm_calls", "tool_calls", "evidence_items", "unknown_weight_pct", "evidenced_weight_pct", "confidence", "unverified_findings"]

    def avg(rows, k):
        vals = [r[k] for r in rows if r.get(k) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def tier(rows, t):
        return f"{sum(r['expect'][t]['passed'] for r in rows)}/{sum(r['expect'][t]['total'] for r in rows)}"

    print(f"{'metric':24} {a['label']:>10} {b['label']:>10}")
    for k in keys:
        print(f"{k:24} {str(avg(a['cases'], k)):>10} {str(avg(b['cases'], k)):>10}")
    print(f"{'core expectations':24} {tier(a['cases'], 'core'):>10} {tier(b['cases'], 'core'):>10}")
    print(f"{'upgrade expectations':24} {tier(a['cases'], 'upgrade'):>10} {tier(b['cases'], 'upgrade'):>10}")
    print("\nper case (duration s / llm calls / verdict score):")
    bi = {r["id"]: r for r in b["cases"]}
    for r in a["cases"]:
        o = bi.get(r["id"], {})
        print(f"  {r['id']:30} {r['duration_s']}s/{r['llm_calls']}/{r['score']}  ->  {o.get('duration_s')}s/{o.get('llm_calls')}/{o.get('score')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--compare", nargs=2)
    args = ap.parse_args()
    if args.compare:
        compare(*args.compare)
    else:
        asyncio.run(run(args.label or "run", args.only))
