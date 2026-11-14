"""Pydantic models. API shapes mirror frontend/lib/api-types.ts; Agent* models are what each LLM
agent must return (validated, then merged by multi_agent_engine.py)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal["vexcel", "neighborhood", "compliance", "cost", "matterport", "engine"]
MetricStatus = Literal["strong", "adequate", "weak", "blocker", "unknown"]


# ------------------------------------------------------------------ API: discovery

class Intent(BaseModel):
    business_type: str = "restaurant"
    business_label: str = "Restaurant"
    location_text: str | None = None
    seats: int | None = None
    sqft: int | None = None
    requirements: list[str] = []
    parser: Literal["ollama", "rules"] = "rules"


class Candidate(BaseModel):
    id: str
    lat: float
    lon: float
    footprint: dict | None = None
    parcel: dict | None = None
    building_type: str | None = None
    area_sqft: float | None = None
    roof_condition: float | None = None
    roof_condition_label: str | None = None
    stories_est: int | None = None
    match_score: int = 0
    match_reasons: list[str] = []
    source: Literal["vexcel", "osm", "demo"] = "vexcel"
    address: str | None = None


class SearchRequest(BaseModel):
    query: str


class SearchResponse(BaseModel):
    intent: Intent
    location: dict | None
    data_mode: Literal["vexcel_live", "vexcel_demo", "osm_only"]
    candidates: list[Candidate]
    notes: list[str] = []


class AnalysisRequest(BaseModel):
    query: str
    intent: Intent
    property_id: str
    radius_m: int = 500
    requirements: str | None = None


# ------------------------------------------------------------------ agent outputs (LLM-facing)

class AgentMetricAssessment(BaseModel):
    metric_id: str = Field(description="One of the metric ids you were assigned")
    status: MetricStatus = Field(description="Choose using the metric's status guide; 'unknown' if evidence is insufficient")
    rationale: str = Field(description="Why this status, tied to the user's business purpose")
    evidence_ids: list[str] = Field(default_factory=list, description="Evidence ids (e.g. E3) from your tool results")
    facts: list[str] = Field(default_factory=list, description="Verified facts from tool results")
    assumptions: list[str] = Field(default_factory=list, description="Assumptions you made")


class AgentFinding(BaseModel):
    title: str
    detail: str
    impact: Literal["positive", "negative", "neutral"]
    severity: Literal["low", "medium", "high"]
    kind: Literal["fact", "inference", "assumption"]
    why_it_matters: str = Field(description="Why this matters for the user's specific business")
    evidence_ids: list[str] = Field(default_factory=list)
    metric_ids: list[str] = Field(default_factory=list)


class AgentOutput(BaseModel):
    summary: str = Field(description="2-3 sentence conclusion for the user's purpose")
    metric_assessments: list[AgentMetricAssessment] = Field(default_factory=list)
    findings: list[AgentFinding] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list, description="Important questions the data cannot answer")
    contradictions: list[str] = Field(default_factory=list, description="Conflicting signals in the evidence")
    followups: list[str] = Field(default_factory=list, description="Concrete next investigations (site visit, ask landlord...)")


# ------------------------------------------------------------------ engine results (API)

class Evidence(BaseModel):
    id: str
    agent: AgentName
    tool: str
    source: str
    url: str | None = None
    summary: str
    data: Any = None


class Finding(AgentFinding):
    id: str
    verified: bool = True


class AgentReport(BaseModel):
    agent: AgentName
    label: str
    status: Literal["completed", "partial", "failed", "skipped"]
    summary: str = ""
    findings: list[Finding] = []
    missing_information: list[str] = []
    contradictions: list[str] = []
    followups: list[str] = []
    tool_calls: int = 0
    duration_s: float = 0
    error: str | None = None
    # internal: raw assessments (merged into metrics by the engine; not part of the public contract)
    metric_assessments: list[AgentMetricAssessment] = Field(default_factory=list, exclude=True)


class MetricResult(BaseModel):
    id: str
    name: str
    category: Literal["common", "dynamic"]
    group: str
    owner_agent: AgentName
    weight: float
    status: MetricStatus
    score: float | None
    why_it_matters: str
    rationale: str
    evidence_ids: list[str] = []
    facts: list[str] = []
    assumptions: list[str] = []
