from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .business_profile import BusinessProfile, Requirements

Status = Literal["PASS", "RISK", "UNKNOWN"]


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
    source: str  # costar | matterport | vexcel | requirements
    note: str | None = None
    confidence: float | None = None
    box: list[float] | None = None  # normalized [x, y, w, h] overlay on the source image


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


class AnalysisResult(BaseModel):
    property_id: str
    address: str
    rank: int
    score: float = Field(..., description="Criteria fit score, 0-100 (higher is better)")
    disqualified: bool
    disqualifiers: list[str] = Field(default_factory=list)
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
    observations: dict[str, Evidence]
    media: dict[str, str | None]
    assumptions: list[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    business_profile: BusinessProfile
    property_ids: list[str] = Field(..., min_length=1)


class AnalyzeResponse(BaseModel):
    business_type: str
    requirements: Requirements
    ranking_basis: str
    results: list[AnalysisResult]
    mode: dict[str, str]
    disclaimer: str
