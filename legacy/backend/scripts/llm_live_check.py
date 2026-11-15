"""Live check of the local LLM against a running Ollama (NOT part of the pytest suite).

Runs the Houston restaurant demo through analyze_properties with the configured LLM and prints the
parsed requirements, the ai_summary and the time each LLM call took.

Usage (from backend/, with `ollama serve` running and the model pulled):
    venv/bin/python scripts/llm_live_check.py
    venv/bin/python scripts/llm_live_check.py --model qwen3:14b --runs 2
    venv/bin/python scripts/llm_live_check.py --details "Opening a taco bar, 30 seats, 2 restrooms"
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.models import BusinessProfile  # noqa: E402
from app.providers import costar_provider  # noqa: E402
from app.services import llm  # noqa: E402
from app.services.agent_orchestrator import analyze_properties  # noqa: E402

DEFAULT_DETAILS = (
    "Opening a ramen shop, about 40 seats, need a full kitchen, two restrooms, budget under $5k a month"
)
HOUSTON_IDS = [f"property-hou-0{i}" for i in range(1, 5)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", help="override OLLAMA_MODEL")
    parser.add_argument("--details", default=DEFAULT_DETAILS)
    parser.add_argument("--runs", type=int, default=1, help="repeat to see warm timings")
    args = parser.parse_args()

    settings.llm_provider = "ollama"
    if args.model:
        settings.ollama_model = args.model
    if not llm.is_available():
        print(f"Ollama not reachable at {settings.ollama_base_url} or {settings.ollama_model} not pulled.")
        return 1

    timings: list[tuple[str, float]] = []
    real_chat = llm.chat_json

    def timed_chat(*a, **k):
        started = time.perf_counter()
        try:
            return real_chat(*a, **k)
        finally:
            timings.append((k.get("purpose", "llm"), time.perf_counter() - started))

    llm.chat_json = timed_chat
    props = [costar_provider.get_property(pid) for pid in HOUSTON_IDS]
    profile = BusinessProfile(type="restaurant", details=args.details, city="Houston", state="TX")

    for run in range(1, args.runs + 1):
        timings.clear()
        started = time.perf_counter()
        response = analyze_properties(profile, props)
        total = time.perf_counter() - started
        print(f"\n=== run {run} / model {llm.label()} / total {total:.2f}s ===")
        print("LLM calls:", ", ".join(f"{p} {t:.2f}s" for p, t in timings))
        print("mode:", response.mode)
        req = response.requirements
        print(
            f"requirements: capacity={req.capacity} {req.capacity_unit}, restrooms={req.bathrooms_required}, "
            f"parking={req.parking_required} ({req.parking_source}), max_rent={req.max_rent}, "
            f"sqft={req.min_sqft}-{req.max_sqft}, kitchen={req.needs_kitchen}"
        )
        for r in response.results:
            print(
                f"  #{r.rank} {r.property_id} {r.address[:30]:<30} score={r.score:5.1f} "
                f"rent=${r.monthly_rent:,.0f} y1=${r.first_year_cost.min:,.0f}-${r.first_year_cost.max:,.0f} "
                f"dq={r.disqualified} weak={r.weak_fit}"
            )
        if response.ai_summary:
            print("\nai_summary:", response.ai_summary.text)
            for pid, sentence in response.ai_summary.per_property.items():
                print(f"  {pid}: {sentence}")
        else:
            print("\nai_summary: null (see log for the reason)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
