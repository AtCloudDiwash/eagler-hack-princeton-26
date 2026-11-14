"""Understand the user's query: business type, size and location.

Rules always run (fast, deterministic); Ollama refines them with constrained JSON output. If Ollama
fails or returns an unknown business type, the rules result is used.
"""
from __future__ import annotations

import asyncio
import logging
import re

from pydantic import BaseModel, Field

from config import business_types
from schemas import Intent
from services.llm import chat_model

log = logging.getLogger("turnkey.intent")

REQUIREMENT_WORDS = {
    "parking": "parking", "accessible": "accessibility", "accessibility": "accessibility", "ada": "accessibility",
    "transit": "transit access", "foot traffic": "foot traffic", "visibility": "visibility", "patio": "outdoor patio",
    "drive-thru": "drive-thru", "drive thru": "drive-thru", "kitchen": "existing kitchen", "cheap": "low cost",
    "affordable": "low cost", "customers": "nearby customers", "quiet": "quiet area",
}


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
        parser="rules",
    )


class _LLMIntent(BaseModel):
    business_type: str = Field(description="One of the allowed business type ids")
    location: str | None = Field(description="City/neighborhood/address mentioned, or null")
    seats: int | None = None
    sqft: int | None = None
    requirements: list[str] = Field(default_factory=list, description="Specific needs stated by the user, short phrases")


async def parse(query: str) -> Intent:
    rules = parse_rules(query)
    types = business_types()
    allowed = ", ".join(f"{k} ({v['label']})" for k, v in types.items())
    prompt = (
        "Extract the user's intent for finding a commercial property.\n"
        f"Allowed business_type ids: {allowed}. Pick the closest one.\n"
        "location: the place they want to be (city, neighborhood or address) exactly as written, or null.\n"
        "seats / sqft: only if stated. requirements: explicit needs (e.g. 'parking', 'near transit').\n"
        f"Query: {query}"
    )
    try:
        llm = chat_model(temperature=0, think=False, num_predict=300).with_structured_output(_LLMIntent, method="json_schema")
        out: _LLMIntent = await asyncio.wait_for(llm.ainvoke(prompt), timeout=25)
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
        requirements=sorted({*rules.requirements, *[r.strip() for r in out.requirements if r.strip()][:6]}),
        parser="ollama",
    )


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
