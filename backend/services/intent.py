"""Understand the user's query: business type, size and location.

Rules always run (fast, deterministic); the LLM (Codex CLI) refines them with schema-constrained JSON. If
the LLM fails or returns an unknown business type, the rules result is used.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from config import business_types, needs_registry
from schemas import Budget, Intent, Need
from services import program, sizing
from services.llm import chat_model

log = logging.getLogger("turnkey.intent")



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
    hits = []  # (start, end, business) for every business keyword in the query
    for key, cfg in types.items():
        for kw in cfg["keywords"]:
            m = re.search(rf"\b{re.escape(kw.lower())}", q)
            if m:
                hits.append((m.start(), m.end(), key))
    # a longer phrase ("dental office") beats a shorter keyword inside it ("office")
    hits = sorted(h for h in hits if not any(o[2] != h[2] and o[0] <= h[0] and h[1] <= o[1] and (o[1] - o[0]) > (h[1] - h[0]) for o in hits))
    best = hits[0][2] if hits else "restaurant"
    # "boutique gym", "dental office": a business word right after the first one is the noun, so it wins
    if len(hits) > 1 and hits[1][2] != best and 0 <= hits[1][0] - hits[0][1] <= 2:
        best = hits[1][2]
    sqft, sqft_min, sqft_max = sizing.parse_size_request(query)
    stop = r"with|for|that|which|and|under|below|within|by|open|must|need|needs|near|close|want|wants|ideally|serving|looking"
    loc = re.search(rf"\b(?:in|near|around|at)\s+([A-Za-z][A-Za-z .,'-]{{1,60}}?)(?:[.?!]|$|,?\s+(?:{stop})\b)", query)
    counts = program.parse_counts(query, best)
    needs = program.parse_needs(query)
    return Intent(
        business_type=best,
        business_label=types[best]["label"],
        location_text=loc.group(1).strip(" ,.") if loc else None,
        seats=counts.get("seats"),
        sqft=sqft,
        sqft_min=sqft_min,
        sqft_max=sqft_max,
        concept=sizing.parse_concept(query, best),
        size_hint=sizing.parse_size_hint(query),
        requirements=sorted(n.label for n in needs),
        budget=parse_budget(query),
        parser="rules",
        occupancy=counts,
        needs=needs,
        open_within_months=program.parse_timeline(query),
        tenure=program.parse_tenure(query),
    )


class _LLMIntent(BaseModel):
    business_type: str = Field(description="One of the allowed business type ids")
    location: str | None = Field(description="City/neighborhood/address mentioned, or null")
    seats: int | None = None
    sqft: int | None = None
    requirements: list[str] = Field(default_factory=list, description="Specific needs stated by the user, short phrases")
    budget_amount: float | None = Field(default=None, description="Budget in US dollars if the user states one, else null")
    budget_period: Literal["monthly", "upfront", "annual"] | None = Field(default=None, description="monthly (rent/occupancy per month), annual, or upfront (one-time build-out/total)")
    staff: int | None = Field(default=None, description="Number of staff/employees on site at once, if stated")
    size_counts: dict[str, int] = Field(default_factory=dict, description="Counts that size the space, keyed by the allowed count fields for this business")
    must_have: list[str] = Field(default_factory=list, description="Need ids (from the allowed list) the user says are required")
    nice_to_have: list[str] = Field(default_factory=list, description="Need ids (from the allowed list) the user mentions as preferences")
    open_within_months: int | None = Field(default=None, description="Months until they want to open, if they state a timeline")
    tenure: Literal["lease", "buy"] = "lease"
    near: list[str] = Field(default_factory=list, description="Places they want to be close to (e.g. 'Rice University')")
    avoid: list[str] = Field(default_factory=list, description="Things they want to avoid nearby")


async def parse(query: str) -> Intent:
    rules = parse_rules(query)
    types = business_types()
    allowed = ", ".join(f"{k} ({v['label']})" for k, v in types.items())
    fields = "; ".join(f"{k}: {', '.join(d['field'] for d in v['program']['drivers']) or 'none'}" for k, v in types.items())
    registry = needs_registry()
    need_ids = ", ".join(f"{k} ({v['label']})" for k, v in registry.items())
    prompt = (
        "Extract the user's intent for finding a commercial property.\n"
        f"Allowed business_type ids: {allowed}. Pick the closest one.\n"
        "location: the place they want to be (city, neighborhood or address) exactly as written, or null.\n"
        "seats / sqft: only if stated. requirements: explicit needs (e.g. 'parking', 'near transit').\n"
        "budget_amount / budget_period: only if the user states a budget (e.g. '$8k a month' = 8000 monthly).\n"
        f"size_counts: counts that size the space. Allowed fields per business: {fields}.\n"
        f"must_have / nice_to_have: ids from this list only: {need_ids}. Required/needed/must = must_have; ideally/prefer = nice_to_have.\n"
        "open_within_months, tenure (buy only if they want to purchase), near, avoid: only if stated.\n"
        f"Today is {date.today():%B %Y}. Query: {query}"
    )
    try:
        llm = chat_model().with_structured_output(_LLMIntent, method="json_schema")
        out: _LLMIntent = await asyncio.wait_for(llm.ainvoke(prompt), timeout=60)
    except Exception as err:  # noqa: BLE001 - any LLM failure falls back to rules
        log.warning("LLM intent parse failed, using rules: %s", err)
        return rules
    if out.business_type not in types:
        return rules
    if out.business_type != rules.business_type:  # counts and concepts depend on the business
        rules = rules.model_copy(update={"occupancy": program.parse_counts(query, out.business_type), "concept": sizing.parse_concept(query, out.business_type)})
    valid_fields = {d["field"] for d in types[out.business_type]["program"]["drivers"]}
    occupancy = {**{k: v for k, v in out.size_counts.items() if k in valid_fields and v and v > 0}, **rules.occupancy}
    if out.staff and "staff" not in occupancy and "staff" not in {kw for d in types[out.business_type]["program"]["drivers"] for kw in d["keywords"]}:
        occupancy["staff"] = out.staff
    if out.seats and "seats" in valid_fields:
        occupancy.setdefault("seats", out.seats)
    needs = {n.id: n for n in rules.needs}
    for nid in out.nice_to_have + out.must_have:  # must_have last so it wins
        if nid in registry and (nid not in needs or nid in out.must_have):
            needs[nid] = Need(id=nid, label=registry[nid]["label"], priority="must" if nid in out.must_have else needs.get(nid, Need(id=nid, label="")).priority)
    extras = [r.strip() for r in out.requirements if r.strip()][:6]
    return Intent(
        business_type=out.business_type,
        business_label=types[out.business_type]["label"],
        location_text=out.location or rules.location_text,
        seats=occupancy.get("seats"),
        # the rules read size qualifiers ("at least", "under", ranges); the LLM's single number only fills a gap
        sqft=rules.sqft or (out.sqft if out.sqft and out.sqft >= 100 else None),
        sqft_min=rules.sqft_min,
        sqft_max=rules.sqft_max,
        concept=rules.concept,
        size_hint=rules.size_hint,
        requirements=_dedupe_requirements([*(n.label for n in needs.values()), *extras]),
        budget=(Budget(amount=out.budget_amount, period=out.budget_period or "upfront", text=rules.budget.text if rules.budget else "")
                if out.budget_amount and out.budget_amount >= 100 else rules.budget),
        parser="llm",
        occupancy=occupancy,
        needs=list(needs.values()),
        open_within_months=rules.open_within_months or (out.open_within_months if out.open_within_months and 0 < out.open_within_months <= 36 else None),
        tenure="buy" if "buy" in (rules.tenure, out.tenure) else "lease",
        near=[n.strip() for n in out.near if n.strip()][:4],
        avoid=[a.strip() for a in out.avoid if a.strip()][:4],
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
    """(target usable sq ft, explanation) from the size estimate (stated sq ft, sizing counts or the concept's typical size)."""
    est = sizing.estimate(intent)
    return est["target_sqft"], est["basis"][0] if est["basis"] else "typical size for this business"
