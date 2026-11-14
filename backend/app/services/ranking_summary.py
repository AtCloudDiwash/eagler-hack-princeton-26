"""Grounded ranking summary: ONE LLM call that explains an already-computed ranking.

The deterministic pipeline (requirements -> compliance -> costs -> rank) runs first. This module
builds a compact JSON digest of that result, asks the configured LLM (app/services/llm.py) for a
plain-English explanation, and then applies a guardrail before anything reaches the user:

* every ``$`` figure in the text must match a number in the digest (within the rounding the text
  uses, at least to the nearest $1k);
* every quoted fit score must match a score in the digest (within 0.5);
* every ``per_property`` key must be a property id from this analysis.

Anything else (no LLM, timeout, invalid JSON, a failed check) yields ``None``; the analysis itself
never fails because of the summary. The LLM never changes costs, scores, statuses or ranks.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from ..config import log
from ..models import AISummary, AnalysisResult, AnalyzeResponse
from . import llm

MAX_NOTES_PER_PROPERTY = 3
MAX_NOTE_CHARS = 140
MAX_TEXT_CHARS = 1500
MAX_SENTENCE_CHARS = 500

SYSTEM_PROMPT = (
    "You explain a ranking of commercial spaces to a small-business owner. The ranking, fit scores, "
    "cost ranges and compliance statuses were already computed by a deterministic engine and are given "
    "to you as a JSON digest, with properties listed in rank order (rank 1 = best).\n"
    "Rules:\n"
    "- Explain only from the digest. Never change the ranking, never contradict a status.\n"
    "- Do not invent numbers. Quote dollar amounts exactly as written in the digest; never add, subtract, "
    "average, multiply or convert them. If unsure of a number, leave it out.\n"
    "- Mention every disqualified property and the reason, and every weak fit. Say whether rent is over "
    "budget only as `rent_vs_budget` states it.\n"
    "- Refer to properties by street address, never by property_id.\n"
    "- Plain English for a non-expert; no markdown, no bullet points, no jargon like 'TI' without explaining it.\n"
    "Output: `summary` = 2-4 short sentences on the overall result and the top pick; `per_property` = exactly "
    "one sentence (under 30 words) per property explaining why it has its rank."
)


# --------------------------------------------------------------------------------------------
# Digest
# --------------------------------------------------------------------------------------------


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _range(lo: float, hi: float) -> str:
    return _money(lo) if round(lo) == round(hi) else f"{_money(lo)} to {_money(hi)}"


def _property_digest(result: AnalysisResult, max_rent: float | None) -> dict[str, Any]:
    descriptions = {c.id: c.description for c in result.criteria_results}
    status = "disqualified" if result.disqualified else "weak fit" if result.weak_fit else "qualifies"
    flagged = [c for c in result.criteria_results if c.status in ("RISK", "UNKNOWN")]
    flagged.sort(key=lambda c: (not c.blocking, -c.weight))
    top_items = sorted(result.line_items, key=lambda i: -i.max)[:3]
    entry: dict[str, Any] = {
        "property_id": result.property_id,
        "rank": result.rank,
        "address": result.address,
        "status": status,
        "fit_score": round(result.score),
        "monthly_rent": _money(result.monthly_rent),
        "first_year_cost": _range(result.first_year_cost.min, result.first_year_cost.max),
        "cost_to_open": _range(result.total_cost_estimate.min, result.total_cost_estimate.max),
        "top_cost_items": [{"item": i.label, "cost": _range(i.min, i.max)} for i in top_items if i.max > 0],
        "flags": [
            {"criterion": c.description, "status": c.status, "note": c.notes[:MAX_NOTE_CHARS]}
            for c in flagged[:MAX_NOTES_PER_PROPERTY]
        ],
    }
    if result.disqualified:
        entry["disqualified_by"] = [descriptions.get(d, d) for d in result.disqualifiers]
    if max_rent:
        over = result.monthly_rent - max_rent
        entry["rent_vs_budget"] = f"{_money(over)} over budget" if over > 0 else "within budget"
    return entry


def build_digest(response: AnalyzeResponse) -> dict[str, Any]:
    """Compact, LLM-friendly view of the response: only facts the summary may use."""
    req = response.requirements
    requirements: dict[str, Any] = {
        "capacity": f"{req.capacity} {req.capacity_unit}",
        "restrooms": req.bathrooms_required,
        "parking_spaces": req.parking_required,
        "needs_kitchen": req.needs_kitchen,
    }
    if req.max_rent:
        requirements["max_monthly_rent"] = _money(req.max_rent)
    if req.min_sqft or req.max_sqft:
        requirements["sqft"] = {"min": req.min_sqft, "max": req.max_sqft}
    return {
        "business": f"{req.business_label} in {req.city}, {req.state}",
        "requirements": requirements,
        "ranking_basis": response.ranking_basis,
        "min_fit_score": response.min_score,
        "properties": [_property_digest(r, req.max_rent) for r in response.results],
    }


def summary_schema(property_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "per_property": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "property_id": {"type": "string", "enum": property_ids},
                        "sentence": {"type": "string"},
                    },
                    "required": ["property_id", "sentence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "per_property"],
        "additionalProperties": False,
    }


# --------------------------------------------------------------------------------------------
# Guardrail
# --------------------------------------------------------------------------------------------

_DIGEST_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_DOLLAR = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k|m|million|thousand)?\b", re.IGNORECASE)
_SCORE = re.compile(
    r"\bscor(?:e|es|ed|ing)\s*(?:of|is|was|at|:|=)?\s*(?:only\s*|just\s*|about\s*)?(\d+(?:\.\d+)?)"
    r"|\b(\d+(?:\.\d+)?)\s*(?:/\s*100|out\s+of\s+100|points?\b|(?:fit\s+)?score\b)",
    re.IGNORECASE,
)
_MULTIPLIER = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}


def _numbers_in(digest: dict[str, Any]) -> list[float]:
    text = json.dumps(digest)
    return [float(m.replace(",", "")) for m in _DIGEST_NUMBER.findall(text)]


def dollar_figures(text: str) -> list[tuple[float, float]]:
    """(value, tolerance) for each $ figure; tolerance = half the precision written, at least $500."""
    figures = []
    for digits, suffix in _DOLLAR.findall(text):
        mult = _MULTIPLIER.get(suffix.lower(), 1) if suffix else 1
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        value = float(digits.replace(",", "")) * mult
        figures.append((value, max(500.0, 0.5 * mult * 10 ** -decimals)))
    return figures


def check_grounded(text: str, digest: dict[str, Any], scores: list[float]) -> str | None:
    """None when every $ figure and quoted score in `text` comes from the digest, else the reason."""
    numbers = _numbers_in(digest)
    for value, tolerance in dollar_figures(text):
        if not any(abs(value - n) <= tolerance for n in numbers):
            return f"dollar figure ${value:,.0f} is not in the digest"
    for a, b in _SCORE.findall(text):
        value = float(a or b)
        if not any(abs(value - s) <= 0.5 for s in scores):
            return f"score {value:g} is not in the digest"
    return None


def validate_summary(data: Any, digest: dict[str, Any], model: str) -> AISummary:
    """Turn raw LLM JSON into an AISummary or raise ValueError (guardrail)."""
    if not isinstance(data, dict):
        raise ValueError("summary is not a JSON object")
    text = " ".join(str(data.get("summary") or "").split())
    if not text:
        raise ValueError("empty summary")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError("summary too long")
    known_ids = {p["property_id"] for p in digest["properties"]}
    per_property: dict[str, str] = {}
    items = data.get("per_property") or []
    if isinstance(items, dict):  # tolerate {id: sentence}
        items = [{"property_id": k, "sentence": v} for k, v in items.items()]
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("per_property item is not an object")
        pid = str(item.get("property_id") or "")
        sentence = " ".join(str(item.get("sentence") or "").split())
        if pid not in known_ids:
            raise ValueError(f"unknown property id {pid!r}")
        if not sentence or len(sentence) > MAX_SENTENCE_CHARS:
            raise ValueError(f"bad sentence for {pid}")
        per_property[pid] = sentence
    scores = [float(p["fit_score"]) for p in digest["properties"]] + [float(digest.get("min_fit_score") or 0)]
    reason = check_grounded(" ".join([text, *per_property.values()]), digest, scores)
    if reason:
        raise ValueError(f"ungrounded summary: {reason}")
    return AISummary(text=text, per_property=per_property, model=model, grounded=True)


# --------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------


def summarize_ranking(response: AnalyzeResponse) -> AISummary | None:
    """One LLM call -> grounded AISummary, or None on any failure (never raises)."""
    if not response.results or not llm.is_available():
        return None
    started = time.perf_counter()
    try:
        digest = build_digest(response)
        ids = [p["property_id"] for p in digest["properties"]]
        data = llm.chat_json(
            SYSTEM_PROMPT,
            "Digest:\n" + json.dumps(digest, separators=(",", ":")),
            summary_schema(ids),
            max_tokens=1024,
            purpose="ranking summary",
        )
        summary = validate_summary(data, digest, llm.label())
    except Exception as exc:  # noqa: BLE001 - the summary is optional; never fail the analysis
        log.warning("AI summary skipped (%s: %s) after %.2fs", type(exc).__name__, exc, time.perf_counter() - started)
        return None
    log.info("AI summary generated by %s in %.2fs", summary.model, time.perf_counter() - started)
    return summary
