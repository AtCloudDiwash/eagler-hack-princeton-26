"""Criteria registry loader (backend/criteria.yaml, or CRITERIA_PATH).

The YAML is re-read whenever it changes on disk (see config.load_yaml), so adding a criterion
or changing a weight takes effect on the next request with no code change.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from ..config import load_yaml, settings
from ..models import Criterion


class CriteriaConfigError(ValueError):
    """criteria.yaml is malformed. The message names the offending entry."""


# path -> (raw YAML object it was parsed from, parsed criteria); identity check avoids re-validation.
_parsed_cache: dict[Path, tuple[object, list[Criterion]]] = {}


def load_criteria(path: Path | None = None) -> list[Criterion]:
    """Parse and validate every entry of the criteria registry."""
    path = Path(path or settings.criteria_path)
    if not path.exists():
        raise CriteriaConfigError(f"Criteria file not found: {path}")
    raw = load_yaml(path)
    cached = _parsed_cache.get(path)
    if cached and cached[0] is raw:
        return cached[1]

    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise CriteriaConfigError(f"{path.name} must be a YAML list of criteria, got {type(raw).__name__}")

    criteria: list[Criterion] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw, start=1):
        label = f"entry #{index}"
        if isinstance(entry, dict) and entry.get("id"):
            label += f" (id '{entry['id']}')"
        if not isinstance(entry, dict):
            raise CriteriaConfigError(f"{path.name} {label}: expected a mapping, got {type(entry).__name__}")
        try:
            criterion = Criterion(**entry)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'entry'}: {err['msg']}" for err in exc.errors()
            )
            raise CriteriaConfigError(f"{path.name} {label} is invalid: {problems}") from exc
        if criterion.id in seen:
            raise CriteriaConfigError(f"{path.name} {label}: duplicate criterion id '{criterion.id}'")
        seen.add(criterion.id)
        criteria.append(criterion)

    _parsed_cache[path] = (raw, criteria)
    return criteria


def get_criterion(criterion_id: str) -> Criterion | None:
    return next((c for c in load_criteria() if c.id == criterion_id), None)


def criteria_by_id() -> dict[str, Criterion]:
    return {c.id: c for c in load_criteria()}


def applies_to_business(criterion: Criterion, business_type: str | None) -> bool:
    if not business_type:
        return True
    types = {t.lower() for t in criterion.business_types}
    return "all" in types or business_type.lower() in types


def applies_to_jurisdiction(criterion: Criterion, city: str | None, state: str | None) -> bool:
    """["ALL"], a state code ("TX") or a city name ("Austin"), case-insensitive."""
    if not city and not state:
        return True
    scopes = {j.strip().lower() for j in criterion.applicable_jurisdictions}
    if "all" in scopes:
        return True
    wanted = {(city or "").strip().lower(), (state or "").strip().lower()} - {""}
    return bool(wanted & scopes)


def applicable_criteria(
    business_type: str | None = None, city: str | None = None, state: str | None = None
) -> list[Criterion]:
    return [
        c
        for c in load_criteria()
        if applies_to_business(c, business_type) and applies_to_jurisdiction(c, city, state)
    ]
