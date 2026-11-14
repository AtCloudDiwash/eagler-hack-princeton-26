from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .business_profile import BusinessProfile, Requirements

Status = Literal["PASS", "RISK", "UNKNOWN"]
EvidenceSource = Literal["costar", "matterport", "vexcel", "requirements", "jurisdiction"]
# Evidence from these sources counts as "observed" for criteria with evidence_required: true.
OBSERVED_SOURCES = frozenset({"costar", "matterport", "vexcel"})


class CostRange(BaseModel):
    min: float
    max: float


class CostLineItem(BaseModel):
    item: str
    label: str
    qty: float
    min: float
    max: float
    reason: str


class Evidence(BaseModel):
    """A single observed or derived fact behind a finding."""

    key: str
    value: Any
    source: EvidenceSource
    note: str | None = None
    confidence: float | None = None
    box: list[float] | None = None  # normalized [x, y, w, h] overlay on the source image
    live: bool = False  # True when the fact came from a live provider call (e.g. Vexcel property/extract)


class CriterionResult(BaseModel):
    id: str
    description: str
    domain: str
    weight: float
    status: Status
    score: float | None = Field(None, description="0..1, or null when excluded from the score")
    counted: bool
    hard_block: bool
    blocking: bool = Field(False, description="True when this result disqualifies the property")
    notes: str
    source: str
    evidence: list[Evidence] = Field(default_factory=list)


class ComplianceStatus(BaseModel):
    status: Status
    notes: str
    source: str = ""


AerialSource = Literal["vexcel-live", "placeholder"]


class Media(BaseModel):
    """Image / tour links for a property. Evidence boxes overlay aerial_url (vexcel) or floor_plan_url (matterport)."""

    aerial_url: str | None = None
    oblique_url: str | None = None  # angled Vexcel photo (live mode only)
    floor_plan_url: str | None = None
    matterport_embed_url: str | None = None
    image_url: str | None = None
    aerial_source: AerialSource = "placeholder"  # "vexcel-live" only when the live ortho image was obtained
    aerial_attribution: str | None = None  # must be shown under live Vexcel imagery


class AnalysisResult(BaseModel):
    property_id: str
    address: str
    listing_source: str | None = Field(
        None, description="Property.listing_source, e.g. 'sample' (demo listing) or 'costar'; null for older runs"
    )
    use_restrictions: list[str] | None = Field(
        None, description="Property.use_restrictions disclosed with the listing; null = not stated / older runs"
    )
    rank: int
    score: float = Field(..., description="Criteria fit score, 0-100 (higher is better)")
    disqualified: bool
    disqualifiers: list[str] = Field(default_factory=list)
    weak_fit: bool = Field(
        False, description="Not disqualified but score < AnalyzeResponse.min_score; ranked after qualifying properties"
    )
    monthly_rent: float
    total_cost_estimate: CostRange = Field(..., description="Cost to open: net fit-out + rent during build-out")
    first_year_cost: CostRange = Field(..., description="Cost to open + rent for the ranking horizon")
    fit_out_estimate: CostRange = Field(..., description="Gross fit-out before any TI allowance")
    ti_allowance: float
    buildout_months: CostRange
    breakdown: dict[str, CostRange]
    line_items: list[CostLineItem]
    compliance: dict[str, ComplianceStatus]
    criteria_results: list[CriterionResult]
    questions_for_landlord: list[str]
    landlord_request: str = Field("", description="Drafted plain-text letter asking for TI allowance / fixes")
    observations: dict[str, Evidence]
    media: Media
    assumptions: list[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    business_profile: BusinessProfile
    property_ids: list[str] = Field(..., min_length=1)


class AnalyzeResponse(BaseModel):
    analysis_id: str = Field(..., description="uuid4 hex; use with GET /api/v1/analyses/{id}")
    created_at: str = Field(..., description="ISO-8601 UTC timestamp")
    business_type: str
    requirements: Requirements
    ranking_basis: str
    min_score: float = Field(0, description="Fit-score threshold below which a property is a weak fit (0 = gate off)")
    results: list[AnalysisResult]
    mode: dict[str, str] = Field(..., description="costar/matterport/vexcel: mock|live, parser: regex|claude")
    disclaimer: str


class AnalysisSummary(BaseModel):
    """One row of GET /api/v1/analyses."""

    analysis_id: str
    created_at: str
    business_type: str
    business_label: str
    city: str
    state: str
    property_count: int
    top_property_id: str | None = None
    top_address: str | None = None
