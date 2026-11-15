"""Weighted criteria score, 0-100.

score = 100 * sum(weight * criterion_score) / sum(weight)   over *counted* criteria only

criterion_score: PASS = 1, RISK = 0, UNKNOWN under assume_risk / assume_cost = 0.
UNKNOWN under unknown / ignore and weight-0 criteria are not counted. Because the denominator
is the total counted weight, adding a criterion to criteria.yaml re-normalizes automatically:
weights are relative and need not sum to 100.
"""
from __future__ import annotations

from collections.abc import Iterable

from ..models import CriterionResult

STATUS_SCORE = {"PASS": 1.0, "RISK": 0.0, "UNKNOWN": 0.0}


def weighted_score(results: Iterable[CriterionResult]) -> float:
    counted = [r for r in results if r.counted and r.score is not None and r.weight > 0]
    total_weight = sum(r.weight for r in counted)
    if total_weight <= 0:
        return 0.0
    return round(100 * sum(r.weight * r.score for r in counted) / total_weight, 1)
