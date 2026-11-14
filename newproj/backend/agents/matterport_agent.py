"""Matterport Agent (optional): interior layout, visible infrastructure and measurements from a 3D scan.

Requires MATTERPORT_API_KEY/SECRET *and* a Matterport model id linked to the property. Property
discovery (Vexcel) does not provide tour ids, so in this build the agent reports itself unavailable and
lists exactly which interior questions remain open; the other agents continue normally.
"""
from __future__ import annotations

from agents.base import AgentReport, RunContext, deterministic_report
from config import settings
from schemas import AgentFinding, AgentMetricAssessment

INTERIOR_QUESTIONS = {
    "restaurant": ["Is there an existing hood, grease interceptor or gas line?", "Ceiling height and clear path for exhaust ductwork", "Restroom count and accessibility"],
    "dental_clinic": ["Room sizes for 4-6 operatories", "Existing plumbing locations (sinks, slab penetrations)", "Electrical panel capacity"],
    "gym": ["Clear ceiling height and column spacing", "Floor type (slab on grade?)", "Locker/shower rooms"],
    "office": ["Open vs. private office layout", "Ceiling height, windows and daylight", "Restrooms and kitchenette"],
    "retail": ["Storefront width and glazing", "Sales floor vs. storage split", "Ceiling height"],
}


def available(ctx: RunContext) -> tuple[bool, str]:
    if not (settings.matterport_api_key and settings.matterport_api_secret):
        return False, "No Matterport API credentials configured (MATTERPORT_API_KEY / MATTERPORT_API_SECRET)."
    if not ctx.property.get("matterport_model_id"):
        return False, "No Matterport tour is linked to this property."
    return True, ""


async def run(ctx: RunContext) -> AgentReport:
    ok, reason = available(ctx)
    questions = INTERIOR_QUESTIONS.get(ctx.intent["business_type"], ["Interior layout and measurements"])
    metrics = ctx.metrics_for("matterport")
    if not ok:
        ctx.emit("matterport", "skipped", f"Skipped: {reason}", None)
        return deterministic_report(
            ctx,
            "matterport",
            f"Interior data unavailable — {reason} Interior layout and infrastructure are unknown and excluded from the score.",
            [AgentMetricAssessment(metric_id=m["id"], status="unknown", rationale=f"No interior scan: {reason}") for m in metrics],
            [AgentFinding(title="Interior not inspected", detail=reason, impact="neutral", severity="medium", kind="fact", why_it_matters="Interior conditions often decide conversion cost; they remain unverified.", metric_ids=[m["id"] for m in metrics])],
            questions,
        )
    # A linked tour would be investigated here via the Matterport Model API (GraphQL). Not reachable in
    # this build because discovery provides no model ids; kept explicit rather than faking data.
    ctx.emit("matterport", "skipped", "Matterport tour linked but model analysis is not implemented in this build", None)
    return deterministic_report(ctx, "matterport", "Matterport model analysis not implemented in this build.", [AgentMetricAssessment(metric_id=m["id"], status="unknown", rationale="Not analyzed") for m in metrics], [], questions)
