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

import db
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
_MONEY_RE = re.compile(
    r"(?P<dollar>\$)?\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<mult>k|m|thousand|million)?\b"
    r"(?P<unit>\s*(?:dollars?|usd|bucks)\b)?"
    r"(?P<tail>(?:\s*(?:/|per|a|an|each)\s*|\s+)(?P<per>month|mo|monthly|year|yr|annually|annum)\b)?",
    re.I,
)
_CUES = ("budget", "under", "below", "max", "up to", "less than", "no more than", "spend", "afford", "within", "cap of", "at most")
_NOT_MONEY = re.compile(r"\s*-?\s*(?:sq\.?\s*ft|sf\b|square|sqft|seat|seater|cover|people|persons?|employees?|staff|stor(?:y|ies)|floors?|minutes?|mins?\b|km\b|miles?\b|meters?\b|m\b)", re.I)


def parse_budgets(text: str) -> list[Budget]:
    """Every budget stated in the text, at most one per period (a later mention of the same period wins).
    Money needs a $ sign, a 'dollars'/'USD' unit, 'budget' just before it, or a k/thousand amount after a cue
    like 'under' / 'max' / 'no more than'. Seats, square feet, distances and staff counts are never money."""
    found: dict[str, Budget] = {}
    for m in _MONEY_RE.finditer(text):
        dollar, unit, mult = m.group("dollar"), m.group("unit"), (m.group("mult") or "").lower()
        rest = text[m.end("num"):]
        if not dollar and not unit and _NOT_MONEY.match(rest if not mult else text[m.end("mult"):]):
            continue
        if mult == "m" and not dollar and not unit:
            continue  # "500 m" is a distance, not $500 million
        before = text[max(0, m.start() - 28): m.start()].lower()
        is_money = bool(dollar or unit or "budget" in before or (mult and any(c in before for c in _CUES)))
        if not is_money:
            continue
        amount = float(m.group("num").replace(",", "")) * _MULT.get(mult, 1)
        if amount < 100:
            continue
        per = (m.group("per") or "").lower()
        after = re.split(r"[,;.]| and | but ", text[m.end(): m.end() + 30].lower())[0]  # only words tied to this amount
        if per.startswith(("y", "ann")) or "per year" in after or "a year" in after:
            period = "annual"
        elif any(w in after for w in ("upfront", "up front", "one-time", "one time", "build", "total", "to open")):
            period = "upfront"
        elif per.startswith(("mo", "month")) or any(w in after for w in ("monthly", "a month", "per month", "rent")):
            period = "monthly"
        else:
            period = "upfront"
        found.pop(period, None)  # keep insertion order = order of the latest mention
        found[period] = Budget(amount=amount, period=period, text=m.group(0).strip())
    return list(found.values())


def parse_budget(query: str) -> Budget | None:
    """The first budget stated in the query (see parse_budgets)."""
    budgets = parse_budgets(query)
    return budgets[0] if budgets else None


def merge_budgets(earlier: list[Budget], later: list[Budget]) -> list[Budget]:
    """One budget per period; the later text wins for the same period."""
    merged = {b.period: b for b in earlier}
    for b in later:
        merged[b.period] = b
    return list(merged.values())


_LOC_PREP = re.compile(r"\b(?:in|near|around|at|by)\s+", re.I)
_LOC_STOP = re.compile(
    r"[.?!;]|\s+(?:in|near|around|at|by)\s+"
    r"|,?\s+(?:with|for|that|which|and|under|below|budget|max|within|where|so|but|need|needs|want|wants|having|has|have|ideally|preferably)\b"
    r"|,?\s*\$|\s+\d[\d,]*\s*(?:[- ]?seat|seater|sq|sf\b|square|k\b|people|employees|staff)",
    re.I,
)


def parse_location(query: str) -> str | None:
    """The place in the query: the text after in/at/near/around, cut at the next clause. With several
    candidates ("interested in opening a bakery in Pasadena", "restaurant in houston near offices") a capitalized
    one wins, then one after in/at (near/around usually describe a need), then the last one."""
    cands = []
    for i, m in enumerate(_LOC_PREP.finditer(query)):
        rest = query[m.end():]
        stop = _LOC_STOP.search(rest)
        text = (rest[: stop.start()] if stop else rest).strip(" ,.'-")
        if 2 <= len(text) <= 60 and (text[0].isalpha() or text[0].isdigit()):
            in_at = m.group(0).strip().lower() in {"in", "at"}
            cands.append(((text[0].isupper() or text[0].isdigit()), in_at, i, text))
    return max(cands)[3] if cands else None


_NEED_SPLIT = re.compile(r"[,;\n]|\.\s|\s+(?:and|also|plus|as well as)\s+", re.I)
_NEED_FILLER = re.compile(r"^(?:and|also|we|i|it|the place|the space|space|must|should|would|need(?:s)? to|need(?:s)?|want(?:s)?|have to|has to|like|prefer(?:ably)?|ideally|must have|should have|have|got|a|an|to be|be|having|with)\b\s*", re.I)


def split_needs(text: str) -> list[str]:
    """Free-text extra requirements -> short need phrases (used when the LLM is unavailable), e.g.
    "need a grease trap, near offices and walkable" -> ["grease trap", "near offices", "walkable"]. Budgets are
    parsed separately and skipped here."""
    out = []
    for part in _NEED_SPLIT.split(text or ""):
        phrase = part.strip(" .!?:-")
        for _ in range(4):
            phrase = _NEED_FILLER.sub("", phrase).strip(" .!?:-")
        if not phrase or "$" in phrase or parse_budgets(phrase) or len(phrase) < 3:
            continue
        out.append(phrase[:60].lower())
    return out


def parse_rules(query: str) -> Intent:
    q = query.lower()
    types = business_types()
    best, best_pos = "restaurant", 10**9
    for key, cfg in types.items():
        for kw in cfg["keywords"]:
            m = re.search(rf"\b{re.escape(kw.lower())}(?:s|es)?\b", q)
            if m and m.start() < best_pos:
                best, best_pos = key, m.start()
    seats = re.search(r"(\d{1,4})\s*[- ]?\s*(?:seat|seater|cover)", q)
    sqft = re.search(r"(\d[\d,]{2,7})\s*(?:sq\.?\s*ft|sf\b|square\s*feet|sqft)", q)
    loc = parse_location(query)
    reqs = sorted({v for k, v in REQUIREMENT_WORDS.items() if k in q})
    budgets = parse_budgets(query)
    return Intent(
        business_type=best,
        business_label=types[best]["label"],
        location_text=loc,
        seats=int(seats.group(1)) if seats else None,
        sqft=int(sqft.group(1).replace(",", "")) if sqft else None,
        requirements=reqs,
        budget=budgets[0] if budgets else None,
        budgets=budgets,
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


_PARSE_CACHE_S = 24 * 3600


async def parse(query: str) -> Intent:
    """Rules + LLM. A successful LLM parse is cached per normalized query, so re-running a search gives the same
    intent (and skips the LLM call)."""
    key = "intent:v2:" + " ".join(query.lower().split())
    if hit := db.cache_get(key, _PARSE_CACHE_S):
        return Intent(**hit)
    intent = await _parse_uncached(query)
    if intent.parser == "llm":
        db.cache_set(key, intent.model_dump())
    return intent


async def _parse_uncached(query: str) -> Intent:
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
        requirements=_dedupe_requirements([*rules.requirements, *[r.strip() for r in out.requirements if r.strip()][:12]]),
        budget=(llm_budget := (Budget(amount=out.budget_amount, period=out.budget_period or "upfront", text=rules.budget.text if rules.budget else "")
                               if out.budget_amount and out.budget_amount >= 100 else None)) or rules.budget,
        budgets=merge_budgets([llm_budget] if llm_budget and llm_budget.period not in {b.period for b in rules.budgets} else [], rules.budgets),
        parser="llm",
    )


def combine_request(query: str, extra: str | None) -> str:
    """The user's full request: the search prompt plus anything added before Analyze."""
    extra = (extra or "").strip()
    return query if not extra else f"{query.strip().rstrip('.')}. Additional requirements: {extra}"


async def refine(intent: Intent, query: str, extra: str | None) -> Intent:
    """Fold the extra requirements typed at analysis time into the intent. The extra text is later and more
    specific, so a budget / seats / size stated there wins; needs are merged. Business type and location stay."""
    extra = (extra or "").strip()
    if not extra:
        return intent
    extra_rules = parse_rules(extra)
    full = await parse(combine_request(query, extra))  # LLM over the combined text (falls back to rules)
    from_llm = full.parser == "llm"
    base_budgets = intent.budgets or ([intent.budget] if intent.budget else [])
    extra_budgets = parse_budgets(extra)
    if not extra_budgets and from_llm and full.budget:
        # The LLM read a budget from the combined text that isn't one of the search's: it came from the extra text.
        if not any(b.period == full.budget.period and abs(b.amount - full.budget.amount) < 1 for b in base_budgets):
            extra_budgets = [full.budget]
    budgets = merge_budgets(base_budgets, extra_budgets)
    budget = extra_budgets[-1] if extra_budgets else intent.budget
    return intent.model_copy(update={
        "seats": extra_rules.seats or (full.seats if from_llm and full.seats != intent.seats else None) or intent.seats,
        "sqft": extra_rules.sqft or (full.sqft if from_llm and full.sqft != intent.sqft else None) or intent.sqft,
        "budget": budget,
        "budgets": budgets,
        "requirements": _dedupe_requirements([*intent.requirements, *full.requirements, *extra_rules.requirements,
                                              *([] if from_llm else split_needs(extra))]),
        "parser": "llm" if from_llm else intent.parser,
    })


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
