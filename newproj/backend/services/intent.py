"""Understand the user's query: business type, size and location.

Rules always run (fast, deterministic); the LLM (Codex CLI) refines them with schema-constrained JSON. If
the LLM fails or returns an unknown business type, the rules result is used.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from config import business_types
from schemas import Budget, Intent
from services.llm import chat_model

log = logging.getLogger("turnkey.intent")

REQUIREMENT_WORDS = {
    "parking": "parking", "accessible": "accessibility", "accessibility": "accessibility", "ada": "accessibility",
    "transit": "transit access", "foot traffic": "foot traffic", "visibility": "visibility", "patio": "outdoor patio",
    "drive-thru": "drive-thru", "drive thru": "drive-thru", "kitchen": "existing kitchen", "cheap": "low cost",
    "affordable": "low cost", "customers": "nearby customers", "quiet": "quiet area",
}


_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}
_BUDGET_RE = re.compile(
    r"(?P<cue>budget(?:\s+(?:of|is|around|about))?\s*:?\s*|under\s+|below\s+|up\s+to\s+|max(?:imum)?\s+|less\s+than\s+|no\s+more\s+than\s+)?"
    r"(?P<dollar>\$)?\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<mult>k|m|thousand|million)?\b"
    r"(?P<tail>(?:\s*(?:/|per|a|an|each)\s*|\s+)(?P<per>month|mo|monthly|year|yr|annually|annum)\b)?",
    re.I,
)


def parse_budget(query: str) -> Budget | None:
    """Budget stated in the query ("$8k/month", "budget of $300,000", "under 5000 a month"). Needs a $ sign or
    a budget cue so seat counts and square footage are never mistaken for money."""
    for m in _BUDGET_RE.finditer(query):
        if not (m.group("dollar") or (m.group("cue") and "budget" in m.group("cue").lower())):
            continue
        amount = float(m.group("num").replace(",", "")) * _MULT.get((m.group("mult") or "").lower(), 1)
        per = (m.group("per") or "").lower()
        after = query[m.end(): m.end() + 30].lower()
        if per.startswith(("mo", "month")) or "monthly" in after or "rent" in after:
            period = "monthly"
        elif per.startswith(("y", "ann")):
            period = "annual"
        else:
            period = "upfront"
        if amount >= 100:
            return Budget(amount=amount, period=period, text=m.group(0).strip())
    return None


def parse_rules(query: str) -> Intent:
    q = query.lower()
    types = business_types()
    best, best_pos = "restaurant", 10**9
    for key, cfg in types.items():
        for kw in cfg["keywords"]:
            m = re.search(rf"\b{re.escape(kw.lower())}", q)
            if m and m.start() < best_pos:
                best, best_pos = key, m.start()
    seats = re.search(r"(\d{1,4})\s*[- ]?\s*(?:seat|seater|cover)", q)
    sqft = re.search(r"(\d[\d,]{2,7})\s*(?:sq\.?\s*ft|sf\b|square\s*feet|sqft)", q)
    loc = re.search(r"\b(?:in|near|around|at)\s+([A-Za-z][A-Za-z .,'-]{1,60}?)(?:[.?!]|$|\s+(?:with|for|that|which|and|under|below)\b)", query)
    reqs = sorted({v for k, v in REQUIREMENT_WORDS.items() if k in q})
    return Intent(
        business_type=best,
        business_label=types[best]["label"],
        location_text=loc.group(1).strip(" ,.") if loc else None,
        seats=int(seats.group(1)) if seats else None,
        sqft=int(sqft.group(1).replace(",", "")) if sqft else None,
        requirements=reqs,
        budget=parse_budget(query),
        parser="rules",
    )


class _LLMIntent(BaseModel):
    business_type: str = Field(description="One of the allowed business type ids")
    location: str | None = Field(description="City/neighborhood/address mentioned, or null")
    seats: int | None = None
    sqft: int | None = None
    requirements: list[str] = Field(default_factory=list, description="Specific needs stated by the user, short phrases")
    budget_amount: float | None = Field(default=None, description="Budget in US dollars if the user states one, else null")
    budget_period: Literal["monthly", "upfront", "annual"] | None = Field(default=None, description="monthly (rent/occupancy per month), annual, or upfront (one-time build-out/total)")


async def parse(query: str) -> Intent:
    rules = parse_rules(query)
    types = business_types()
    allowed = ", ".join(f"{k} ({v['label']})" for k, v in types.items())
    prompt = (
        "Extract the user's intent for finding a commercial property.\n"
        f"Allowed business_type ids: {allowed}. Pick the closest one.\n"
        "location: the place they want to be (city, neighborhood or address) exactly as written, or null.\n"
        "seats / sqft: only if stated. requirements: explicit needs (e.g. 'parking', 'near transit').\n"
        "budget_amount / budget_period: only if the user states a budget (e.g. '$8k a month' = 8000 monthly).\n"
        f"Query: {query}"
    )
    try:
        llm = chat_model().with_structured_output(_LLMIntent, method="json_schema")
        out: _LLMIntent = await asyncio.wait_for(llm.ainvoke(prompt), timeout=60)
    except Exception as err:  # noqa: BLE001 - any LLM failure falls back to rules
        log.warning("LLM intent parse failed, using rules: %s", err)
        return rules
    if out.business_type not in types:
        return rules
    return Intent(
        business_type=out.business_type,
        business_label=types[out.business_type]["label"],
        location_text=out.location or rules.location_text,
        seats=out.seats or rules.seats,
        sqft=out.sqft or rules.sqft,
        requirements=_dedupe_requirements([*rules.requirements, *[r.strip() for r in out.requirements if r.strip()][:6]]),
        budget=(Budget(amount=out.budget_amount, period=out.budget_period or "upfront", text=rules.budget.text if rules.budget else "")
                if out.budget_amount and out.budget_amount >= 100 else rules.budget),
        parser="llm",
    )


def _dedupe_requirements(items: list[str]) -> list[str]:
    """Merge rule + LLM requirements, dropping ones contained in a longer phrase ("foot traffic" vs "good foot traffic")."""
    uniq = sorted({i.lower() for i in items}, key=len, reverse=True)
    kept: list[str] = []
    for item in uniq:
        if not any(item in k for k in kept):
            kept.append(item)
    return sorted(kept)


def target_sqft(intent: Intent) -> tuple[int, str]:
    """(target usable sq ft, explanation) from seats/sqft or the business default."""
    cfg = business_types()[intent.business_type]["sizing"]
    if intent.sqft:
        return intent.sqft, f"{intent.sqft:,} sq ft requested"
    if intent.seats and cfg.get("sqft_per_seat"):
        sq = intent.seats * cfg["sqft_per_seat"]
        return sq, f"{intent.seats} seats × {cfg['sqft_per_seat']} sq ft/seat (incl. kitchen & back of house)"
    if cfg.get("default_seats") and cfg.get("sqft_per_seat"):
        sq = cfg["default_seats"] * cfg["sqft_per_seat"]
        return sq, f"default {cfg['default_seats']} seats × {cfg['sqft_per_seat']} sq ft/seat"
    return cfg.get("default_sqft", 2500), "typical size for this business"
