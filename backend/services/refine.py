"""Refine a search in conversation: the user keeps talking to the agent until the matches look right.

Each follow-up ("make it 60 seats", "only ground floor", "drop parking", "budget $8k a month", "near Rice") is
applied to the CURRENT search, not parsed from scratch, so everything the user didn't mention is kept. A question
about the current matches ("which ones are on the ground floor?") is answered from the matches the client sends,
without re-running the search. The LLM proposes; Python decides what actually changed (the change chips come from
a deterministic diff of the old and new search), and the rules parser is the fallback when no LLM answers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date
from typing import Literal

from pydantic import Field

from config import business_types, needs_registry
from schemas import Budget, Intent, Need
from services.intent import _LLMIntent, _dedupe_requirements, parse_rules
from services.llm import chat_model

log = logging.getLogger("turnkey.refine")


class _Refinement(_LLMIntent):
    action: Literal["refine", "answer"] = Field(description="'refine' when the message changes what to search for; 'answer' when it only asks about the current matches")
    reply: str = Field(description="One or two short sentences to the user, past tense: what you changed (the app adds the new match count, so don't), or the answer to their question (name buildings by title)")
    concept: str | None = None
    size_hint: Literal["small", "large"] | None = None
    sqft_min: int | None = None
    sqft_max: int | None = None
    clear_fields: list[str] = Field(default_factory=list, description="Fields the user explicitly asked to clear, e.g. sqft_min, sqft_max, concept, size_hint, budget")
    drop_requirements: list[str] = Field(default_factory=list, description="Free-text requirements explicitly removed by the user")
    drop_needs: list[str] = Field(default_factory=list, description="Need ids the user no longer wants")


def _current(prev: Intent) -> dict:
    registry_labels = {n.label.lower() for n in prev.needs}
    return {
        **prev.model_dump(include={"concept", "size_hint", "sqft_min", "sqft_max"}),
        "business_type": prev.business_type,
        "location": prev.location_text,
        "seats": prev.seats,
        "sqft": prev.sqft,
        "size_counts": prev.occupancy,
        "budget_amount": prev.budget.amount if prev.budget else None,
        "budget_period": prev.budget.period if prev.budget else None,
        "must_have": [n.id for n in prev.needs if n.priority == "must"],
        "nice_to_have": [n.id for n in prev.needs if n.priority == "nice"],
        "requirements": [r for r in prev.requirements if r.lower() not in registry_labels],
        "open_within_months": prev.open_within_months,
        "tenure": prev.tenure,
        "near": prev.near,
        "avoid": prev.avoid,
    }


def describe_changes(prev: Intent, new: Intent) -> list[str]:
    """Readable, deterministic list of what differs between two searches (the chips shown under the reply)."""
    out: list[str] = []
    types = business_types()
    if new.business_type != prev.business_type:
        out.append(f"{types.get(prev.business_type, {}).get('label', prev.business_type)} → {new.business_label}")
    if (new.location_text or "") != (prev.location_text or ""):
        out.append(f"Area: {new.location_text or 'Houston, TX'}")
    for field, label in (("seats", "seats"), ("sqft", "sq ft")):
        a, b = getattr(prev, field), getattr(new, field)
        if a != b:
            out.append(f"{b:,} {label}" if b else f"no {label} target")
    for k in sorted(set(prev.occupancy) | set(new.occupancy)):
        if k != "seats" and prev.occupancy.get(k) != new.occupancy.get(k):
            out.append(f"{new.occupancy[k]} {k.replace('_', ' ')}" if new.occupancy.get(k) else f"no {k.replace('_', ' ')}")
    pb, nb = prev.budget, new.budget
    if ((pb.amount, pb.period) if pb else None) != ((nb.amount, nb.period) if nb else None):
        out.append(f"Budget ${nb.amount:,.0f} {nb.period}" if nb else "No budget")
    before = {n.id: n.priority for n in prev.needs}
    after = {n.id: n for n in new.needs}
    for nid, n in after.items():
        if nid not in before:
            out.append(f"+ {n.label}" + (" (must)" if n.priority == "must" else ""))
        elif before[nid] != n.priority:
            out.append(f"{n.label}: {'must-have' if n.priority == 'must' else 'nice-to-have'}")
    out += [f"− {n.label}" for n in prev.needs if n.id not in after]
    if new.open_within_months != prev.open_within_months:
        out.append(f"Open in ~{new.open_within_months} months" if new.open_within_months else "No timeline")
    if new.tenure != prev.tenure:
        out.append("Buying" if new.tenure == "buy" else "Leasing")
    for field, label in (("near", "Near"), ("avoid", "Avoid")):
        added = [x for x in getattr(new, field) if x not in getattr(prev, field)]
        if added:
            out.append(f"{label}: {', '.join(added)}")
        removed = [x for x in getattr(prev, field) if x not in getattr(new, field)]
        if removed:
            out.append(f"Removed {label.lower()}: {', '.join(removed)}")
    for field in ("concept", "size_hint", "sqft_min", "sqft_max"):
        if getattr(prev, field) != getattr(new, field):
            out.append(f"{field.replace('_', ' ').capitalize()}: {getattr(new, field) or 'removed'}")
    labels = {n.label.lower() for n in [*prev.needs, *new.needs]}
    before_req = {r for r in prev.requirements if r.lower() not in labels}
    after_req = {r for r in new.requirements if r.lower() not in labels}
    out.extend(f"+ {r} (check during analysis)" for r in sorted(after_req - before_req))
    out.extend(f"− {r}" for r in sorted(before_req - after_req))
    return out


def _intent_from(out: _Refinement, prev: Intent) -> Intent:
    types, registry = business_types(), needs_registry()
    btype = out.business_type if out.business_type in types else prev.business_type
    valid = {d["field"] for d in types[btype]["program"]["drivers"]}
    counts = {k: v for k, v in (out.size_counts or {}).items() if (k in valid or k == "staff") and v and v > 0}
    if out.seats and "seats" in valid:
        counts["seats"] = out.seats
    if out.staff:
        counts["staff"] = out.staff
    if not counts and btype == prev.business_type and not out.sqft:
        counts = dict(prev.occupancy)  # the model left the size out: keep the current one
    needs: dict[str, Need] = {n.id: n for n in prev.needs if n.id not in out.drop_needs}
    for nid in [*out.nice_to_have, *out.must_have]:
        if nid in registry and nid not in out.drop_needs:
            needs[nid] = Need(id=nid, label=registry[nid]["label"], priority="must" if nid in out.must_have else "nice")
    # Free-text extras that restate a structured need ("ground floor spaces only" vs the ground_floor need) are dropped.
    need_words = [kw.lower() for nid in needs for kw in [registry[nid]["label"], *registry[nid].get("keywords", [])]]
    extras = [r.strip() for r in (out.requirements if "requirements" in out.model_fields_set else prev.requirements) if r.strip() and r not in out.drop_requirements and not any(w in r.lower() or r.lower() in w for w in need_words)][:6]
    previous_extras = [r for r in prev.requirements if r.lower() not in {n.label.lower() for n in prev.needs} and r not in out.drop_requirements]
    extras = _dedupe_requirements([*previous_extras, *extras])
    budget = prev.budget
    if out.budget_amount and out.budget_amount >= 100:
        same = prev.budget and prev.budget.amount == out.budget_amount and prev.budget.period == (out.budget_period or prev.budget.period)
        budget = prev.budget if same else Budget(amount=out.budget_amount, period=out.budget_period or "monthly", text="")
    new = Intent(
        business_type=btype,
        business_label=types[btype]["label"],
        location_text=out.location or None,
        seats=counts.get("seats"),
        sqft=out.sqft or None,
        requirements=_dedupe_requirements([*(n.label for n in needs.values()), *extras]),
        budget=budget,
        parser="llm",
        occupancy=counts,
        needs=list(needs.values()),
        open_within_months=out.open_within_months if out.open_within_months and 0 < out.open_within_months <= 36 else None,
        tenure=out.tenure,
        near=[n.strip() for n in out.near if n.strip()][:4],
        avoid=[a.strip() for a in out.avoid if a.strip()][:4],
    )

    # Structured outputs may omit optional fields. Merge only fields actually supplied.
    mapping = {"location": "location_text", "open_within_months": "open_within_months",
               "tenure": "tenure", "near": "near", "avoid": "avoid", "sqft": "sqft"}
    update = new.model_dump()
    for source, dest in mapping.items():
        if source not in out.model_fields_set:
            update[dest] = getattr(prev, dest)
    for field in ("concept", "size_hint", "sqft_min", "sqft_max"):
        update[field] = getattr(out, field) if getattr(out, field) is not None else getattr(prev, field)
    if out.sqft is None and "sqft" not in out.clear_fields:
        update["sqft"] = prev.sqft
    for field in out.clear_fields:
        if field in {"concept", "size_hint", "sqft", "sqft_min", "sqft_max", "location_text", "open_within_months"}:
            update[field] = None
    if "budget" in out.clear_fields:
        budget = None
    return prev.model_copy(update={**update, "budget": budget, "needs": list(needs.values())})


_DROP_RE = re.compile(r"\b(?:no|without|drop|remove|don'?t need|do not need|forget)\b", re.I)


def _rules_refine(prev: Intent, message: str) -> Intent:
    """Fallback without an LLM: apply what the rules parser finds in the message on top of the current search."""
    r = parse_rules(message)
    upd: dict = {"parser": "rules"}
    if r.seats:
        upd["seats"] = r.seats
        upd["occupancy"] = {**prev.occupancy, "seats": r.seats}
    elif r.occupancy:
        upd["occupancy"] = {**prev.occupancy, **r.occupancy}
    if r.sqft or r.sqft_min or r.sqft_max:
        upd.update(sqft=r.sqft, sqft_min=r.sqft_min, sqft_max=r.sqft_max)
    if r.concept:
        upd["concept"] = r.concept
    if r.size_hint:
        upd["size_hint"] = r.size_hint
    if r.budget:
        upd["budget"] = r.budget
    if r.location_text:
        upd["location_text"] = r.location_text
    if r.open_within_months:
        upd["open_within_months"] = r.open_within_months
    needs = {n.id: n for n in prev.needs}
    for n in r.needs:
        if _DROP_RE.search(message):
            needs.pop(n.id, None)
        else:
            needs[n.id] = n
    upd["needs"] = list(needs.values())
    upd["requirements"] = _dedupe_requirements([*(n.label for n in needs.values()), *[x for x in prev.requirements if x.lower() not in {n.label.lower() for n in prev.needs}]])
    return prev.model_copy(update=upd)


async def refine(prev: Intent, message: str, history: list[dict] | None = None, matches: list[dict] | None = None) -> dict:
    """{"action": "refine"|"answer", "reply", "changes": [..], "intent": Intent}. Never raises."""
    types, registry = business_types(), needs_registry()
    convo = "\n".join(f"{t.get('role', 'user').upper()}: {str(t.get('text', ''))[:300]}" for t in (history or [])[-8:])
    prompt = (
        "You help a small-business owner narrow down a search for a commercial space. They refine it in conversation.\n"
        f"CURRENT SEARCH (JSON): {json.dumps(_current(prev))}\n"
        f"CURRENT TOP MATCHES (JSON): {json.dumps((matches or [])[:12], default=str)}\n"
        + (f"CONVERSATION SO FAR:\n{convo}\n" if convo else "")
        + f"NEW MESSAGE: {message}\n\n"
        "If the message changes what to look for (size, seats, budget, area, business type, must-haves, timeline, near/avoid), "
        "set action='refine' and return the COMPLETE updated search: copy every field from CURRENT SEARCH that the user did not change, "
        "apply their change, list fields explicitly removed in clear_fields, free-text requirements removed in drop_requirements, and need ids they no longer want in drop_needs. If the message only asks about the current matches, "
        "set action='answer', copy CURRENT SEARCH unchanged and answer from CURRENT TOP MATCHES only (never invent buildings or numbers).\n"
        f"Allowed business_type ids: {', '.join(types)}. Need ids: {', '.join(f'{k} ({v['label']})' for k, v in registry.items())}.\n"
        f"Today is {date.today():%B %Y}."
    )
    try:
        llm = chat_model().with_structured_output(_Refinement, method="json_schema")
        out: _Refinement = await asyncio.wait_for(llm.ainvoke(prompt), timeout=60)
    except Exception as err:  # noqa: BLE001 - fall back to the rules parser
        log.warning("refine LLM failed, using rules: %s", err)
        new = _rules_refine(prev, message)
        changes = describe_changes(prev, new)
        reply = ("Updated your search: " + ", ".join(changes) + "." if changes else "I couldn't find a change to apply in that; try e.g. '60 seats', 'budget $8k a month' or 'must have parking'.")
        return {"action": "refine" if changes else "answer", "reply": reply + " (AI unavailable, so I used the quick parser.)", "changes": changes, "intent": new}
    if out.action == "answer":
        return {"action": "answer", "reply": out.reply.strip() or "Here's what I see in the current matches.", "changes": [], "intent": prev}
    new = _intent_from(out, prev)
    from services.sizing import parse_size_request
    sqft, lower, upper = parse_size_request(message)
    if any(v is not None for v in (sqft, lower, upper)):
        new = new.model_copy(update={"sqft": sqft, "sqft_min": lower, "sqft_max": upper})
    changes = describe_changes(prev, new)
    if not changes:  # nothing actually changed: don't re-run the search
        return {"action": "answer", "reply": out.reply.strip() or "Your search already matches that.", "changes": [], "intent": prev}
    extras_only = prev.model_dump(exclude={"requirements", "parser", "avoid"}) == new.model_dump(exclude={"requirements", "parser", "avoid"})
    reply = "Saved your analysis requirements; they do not affect discovery ranking." if extras_only else (out.reply.strip() or "Updated your search.")
    return {"action": "refine", "reply": reply, "changes": changes, "intent": new}
