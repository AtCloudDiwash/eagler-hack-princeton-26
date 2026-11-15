"""Pydantic models. API shapes mirror frontend/lib/api-types.ts; Agent* models are what each LLM
agent must return (validated, then merged by multi_agent_engine.py)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal["vexcel", "neighborhood", "compliance", "cost", "matterport", "engine"]
MetricStatus = Literal["strong", "adequate", "weak", "blocker", "unknown"]


# ------------------------------------------------------------------ API: discovery

class Budget(BaseModel):
    amount: float
    period: Literal["monthly", "upfront", "annual"]
    text: str = ""


class Need(BaseModel):
    id: str  # key in config/needs.yaml
    label: str
    priority: Literal["must", "nice"] = "nice"


class Intent(BaseModel):
    business_type: str = "restaurant"
    business_label: str = "Restaurant"
    location_text: str | None = None
    seats: int | None = None
    sqft: int | None = None
    sqft_min: int | None = None  # "at least 2,000 sq ft", "1,200-1,800 sq ft" (services/sizing.py)
    sqft_max: int | None = None  # "under 1,500 sq ft"
    concept: str | None = None  # business concept (coffee shop, fine dining, yoga studio...); None = the default
    size_hint: Literal["small", "large"] | None = None  # "small cafe", "large gym" when no count is given
    requirements: list[str] = []  # readable labels of everything asked for (needs + free-text extras)
    budget: Budget | None = None
    parser: Literal["llm", "rules"] = "rules"
    # Space program inputs (services/program.py)
    occupancy: dict[str, int] = {}  # counts stated in the request: seats, chairs, members, class_size, employees, staff
    needs: list[Need] = []  # recognised needs (config/needs.yaml), must-have or nice-to-have
    open_within_months: int | None = None  # "open by spring", "within 3 months"
    tenure: Literal["lease", "buy"] = "lease"
    near: list[str] = []  # places the user wants to be close to ("near Rice University")
    avoid: list[str] = []  # things to stay away from ("not next to a bar")


class Candidate(BaseModel):
    id: str
    lat: float
    lon: float
    footprint: dict | None = None
    parcel: dict | None = None
    building_type: str | None = None
    area_sqft: float | None = None  # BUILDING FOOTPRINT: the building's outline from above (~one floor), not the parcel or a leasable suite
    floor_area_est_sqft: float | None = None  # footprint × estimated stories (rough total floor area of the building)
    parcel_sqft: float | None = None  # the property: lot/parcel area
    roof_condition: float | None = None
    roof_condition_label: str | None = None
    stories_est: int | None = None
    match_score: int = 0
    match_reasons: list[str] = []
    distance_m: float | None = None  # from the searched place
    source: Literal["vexcel", "osm", "demo", "costar"] = "vexcel"
    address: str | None = None
    # CoStar (sponsor kit): the leasing figures Vexcel can't measure
    costar_id: int | None = None
    building_name: str | None = None
    rentable_sqft: float | None = None  # Rentable Building Area (RBA; GLA for retail): the whole building's rentable area
    rentable_basis: str | None = None  # "RBA" | "GLA"
    available_sqft: float | None = None  # sum of spaces on the market (not lease-pending)
    space_count: int = 0  # spaces on the market
    best_space: dict | None = None  # the listed suite closest to the user's size: suite, floor, sqft (sqft_min when divisible), rent_per_sqft_yr
    closest_space_sqft: float | None = None  # when no listed suite is in range: the listed space nearest the user's size
    asking_rent_per_sqft_yr: list[float] | None = None  # [low, high] across listed spaces


class SearchRequest(BaseModel):
    query: str


class SearchResponse(BaseModel):
    intent: Intent
    location: dict | None
    data_mode: Literal["vexcel_live", "vexcel_demo", "osm_only"]
    candidates: list[Candidate]
    notes: list[str] = []
    program: dict | None = None  # what the request implies: size, occupancy, code needs, building needs


class MapCenter(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class MapAnchor(BaseModel):
    """What follow-up questions are about ("around it", "near there"): a clicked place, an area or the map view."""
    kind: Literal["place", "area", "view"] = "place"
    id: str | None = None
    label: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class MapContext(BaseModel):
    """The map's current conversational state, so follow-ups ("which is closest?", "the second one") resolve."""
    anchor: MapAnchor | None = None
    radius_m: int | None = Field(default=None, ge=50, le=1500)  # None: everything the place data covers
    interaction: str | None = None  # the previous interaction type
    places: list[dict] = []  # places currently shown, in display order (id, name, group, category, lat, lon)


class RefineRequest(BaseModel):
    """A follow-up message on the current search ("make it 60 seats", "which ones have parking?")."""
    intent: Intent  # the current search
    message: str
    property_id: str | None = None
    center: MapCenter | None = None
    history: list[dict] = []  # earlier turns: [{"role": "user"|"agent", "text": ...}]
    matches: list[dict] = []  # the current top matches, summarized by the client (lets the agent answer questions)
    map_context: MapContext | None = None


class RefineResponse(BaseModel):
    action: Literal["refine", "answer", "map"]  # map: read-only map/place action; refine: updated requirements; answer: reply only
    reply: str
    changes: list[str] = []  # what changed in the search (deterministic diff)
    map_action: dict | None = None
    result: SearchResponse | None = None  # the new results when action == "refine"


class MatterportLinkRequest(BaseModel):
    tour: str = Field(description="Matterport showcase URL (…/show/?m=<id>) or bare model id")


class AnalysisRequest(BaseModel):
    query: str
    intent: Intent
    property_id: str
    selection: dict | None = None
    conversation_history: list[dict] = []
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


class NeedCheck(BaseModel):
    need_id: str = Field(description="Id of a stated need you were asked to check (from NEEDS YOU MUST CHECK)")
    status: Literal["met", "unmet", "unknown"] = Field(description="'met'/'unmet' only with evidence; otherwise 'unknown'")
    detail: str = Field(default="", description="One sentence: what the evidence shows, or how to verify it")
    evidence_ids: list[str] = Field(default_factory=list)


class AgentOutput(BaseModel):
    summary: str = Field(description="2-3 sentence conclusion for the user's purpose")
    metric_assessments: list[AgentMetricAssessment] = Field(default_factory=list)
    needs: list[NeedCheck] = Field(default_factory=list, description="One entry per stated need you were asked to check")
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
    needs: list[NeedCheck] = []  # one per stated need this agent owns (unknown when it did not report it)
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
