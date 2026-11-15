"""All numeric scoring lives here (never in an LLM). Agents give each metric a status with evidence;
these functions turn statuses into scores, confidence and a verdict."""
from __future__ import annotations

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
