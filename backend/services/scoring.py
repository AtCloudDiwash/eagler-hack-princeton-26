"""All numeric scoring lives here (never in an LLM). Agents give each metric a status with evidence;
these functions turn statuses into scores, confidence and a verdict."""
from __future__ import annotations

import re

STATUS_POINTS = {"strong": 100, "adequate": 70, "weak": 35, "blocker": 0}
VERDICT_LABELS = {
    "recommended": "Recommended",
    "conditional": "Recommended with conditions",
    "not_recommended": "Not recommended",
    "insufficient_evidence": "Insufficient evidence",
}
THRESHOLDS = {"recommended": 72, "conditional": 50, "min_confidence": 40}


def metric_score(status: str, verified: bool) -> float | None:
    """Points for a status; unverified claims (no valid evidence) are pulled toward neutral."""
    pts = STATUS_POINTS.get(status)
    if pts is None:
        return None
    return float(pts) if verified else round(pts * 0.6 + 50 * 0.4, 1)


def overall(metrics: list[dict]) -> dict:
    """metrics: [{weight, status, score, evidence_ids, hard_block}] -> score, confidence, verdict."""
    scored = [m for m in metrics if m["weight"] > 0]
    total_w = sum(m["weight"] for m in scored) or 1
    known = [m for m in scored if m["score"] is not None]
    known_w = sum(m["weight"] for m in known)
    score = round(sum(m["weight"] * m["score"] for m in known) / known_w) if known_w else 0
    evidenced_w = sum(m["weight"] for m in known if m["evidence_ids"])
    confidence = round(100 * evidenced_w / total_w)
    blockers = [m for m in scored if m["status"] == "blocker" and m.get("hard_block")]
    if blockers:
        verdict = "not_recommended"
    elif confidence < THRESHOLDS["min_confidence"]:
        verdict = "insufficient_evidence"
    elif score >= THRESHOLDS["recommended"] and not any(m["status"] in {"weak", "blocker"} and m["weight"] >= 10 for m in scored):
        verdict = "recommended"
    elif score >= THRESHOLDS["conditional"]:
        verdict = "conditional"
    else:
        verdict = "not_recommended"
    return {"score": score, "confidence": confidence, "verdict": verdict, "label": VERDICT_LABELS[verdict], "blockers": [m["id"] for m in blockers]}


def evidence_quality_status(confidence: int) -> str:
    return "strong" if confidence >= 75 else "adequate" if confidence >= 55 else "weak"


# ---------------------------------------------------------------- the user's own requirements
# The needs the user typed (search prompt + extra requirements) are part of the score, and they can cap the
# verdict: a property that misses what the user asked for is never "Recommended", whatever its other metrics say.
REQUIREMENT_WEIGHT = 8  # per checked requirement (a typical metric weighs 5-15)
REQUIREMENT_WEIGHT_CAP = 32  # all requirements together
ORDER = ["not_recommended", "insufficient_evidence", "conditional", "recommended"]


def requirement_rows(checks: list[dict]) -> list[dict]:
    """Scoring rows for requirements judged met/unmet (unknown ones are reported, not scored)."""
    known = [c for c in checks if c["status"] in {"met", "unmet"}]
    if not known:
        return []
    weight = min(REQUIREMENT_WEIGHT, REQUIREMENT_WEIGHT_CAP / len(known))
    return [{"id": f"requirement:{c['requirement']}", "weight": weight, "status": "strong" if c["status"] == "met" else "weak",
             "score": 100.0 if c["status"] == "met" else 0.0, "evidence_ids": c.get("evidence_ids") or [], "hard_block": False}
            for c in known]


def cap_for_requirements(rec: dict, checks: list[dict], budgets: list[dict]) -> dict:
    """Cap the verdict when the property misses what the user explicitly asked for. Returns a new rec with
    'caps' (plain-language reasons)."""
    caps: list[tuple[str, str]] = []
    stated_budget = any(b.get("source") == "user" for b in budgets)
    # A budget phrased as a requirement ("budget under $80k") is judged by the budget check below, not twice.
    unmet = [c["requirement"] for c in checks if c["status"] == "unmet" and c.get("priority") != "nice"  # nice-to-haves only lower the score
             and not (stated_budget and re.search(r"budget|\$|\bcost|afford|cheap", c["requirement"], re.I))]
    if len(unmet) >= 2:
        caps.append(("not_recommended", f"It misses {len(unmet)} of your stated requirements ({', '.join(unmet)})."))
    elif unmet:
        caps.append(("conditional", f"It misses your stated requirement: {unmet[0]}."))
    for b in budgets:
        if b.get("source") != "user" or b["status"] != "over":
            continue
        over_by = b["compare_low"] / b["amount"] - 1 if b["amount"] else 0
        text = f"Even the low estimate (${b['compare_low']:,.0f}) is over your {b['period']} budget of ${b['amount']:,.0f}"
        if over_by >= 0.5:
            caps.append(("not_recommended", f"{text}, by {over_by:.0%}."))
        else:
            caps.append(("conditional", f"{text}."))
    out = {**rec, "caps": [reason for _, reason in caps]}
    for level, _ in caps:
        if ORDER.index(level) < ORDER.index(out["verdict"]):  # only ever lowers the verdict
            out["verdict"], out["label"] = level, VERDICT_LABELS[level]
    return out
