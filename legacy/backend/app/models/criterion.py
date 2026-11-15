from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

MissingDataPolicy = Literal["assume_risk", "assume_cost", "unknown", "ignore"]


class Criterion(BaseModel):
    """One entry of backend/criteria.yaml. See docs/CRITERIA_REGISTRY.md."""

    id: str
    description: str
    domain: str
    weight: float = Field(0, ge=0)
    hard_block: bool = False
    evaluator: str
    required_inputs: list[str] = Field(default_factory=list)
    missing_data_policy: MissingDataPolicy = "assume_risk"
    evidence_required: bool = False
    source: str = ""
    thresholds: dict[str, Any] = Field(default_factory=dict)
    business_types: list[str] = Field(default_factory=lambda: ["ALL"])
    applicable_jurisdictions: list[str] = Field(default_factory=lambda: ["ALL"])

    @field_validator("thresholds", mode="before")
    @classmethod
    def _none_to_dict(cls, value: Any) -> Any:
        return value or {}
