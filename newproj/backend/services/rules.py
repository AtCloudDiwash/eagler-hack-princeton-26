"""Deterministic compliance lookups over config/jurisdictions.yaml (verified rules only).

The Compliance Agent calls these as tools. Anything not in the rule set comes back "unknown" with
the official place to check: the agent can interpret, but it cannot invent regulations.
"""
from __future__ import annotations

import math

from config import business, jurisdictions
from services.geo import point_in_polygon

SQFT_PER_SPACE = 325  # paved sq ft per parking space incl. aisles (planning rule of thumb)


def jurisdiction_for(city: str | None, state: str | None) -> tuple[str, dict]:
    c, s = (city or "").strip().lower(), (state or "").strip().lower()
    for key, j in jurisdictions().items():
        if key.startswith("_"):
            continue
        m = j.get("match", {})
        if c in m.get("city", []) and s in m.get("state", []):
            return key, j
    return "_default", jurisdictions()["_default"]


def permitted_use(jur: dict, business_type: str) -> dict:
    use = business(business_type)["zoning_use"]
    rule = jur["permitted_use"].get(use) or jur["permitted_use"]["_default"]
    return {
        "id": "permitted_use",
        "rule": f"Permitted use: {business(business_type)['label'].lower()}",
        "status": rule["status"],
        "detail": rule["detail"].strip(),
        "citation": rule.get("citation"),
        "url": rule.get("url"),
        "zoning_mode": jur.get("zoning_mode"),
    }


def parking_requirement(jur: dict, business_type: str, gfa_sqft: float | None, lat: float, lon: float, paved_sqft: float | None) -> dict:
    use = business(business_type)["zoning_use"]
    p = jur["parking"]
    out = {"id": "parking_requirement", "rule": "Off-street parking minimum", "citation": p.get("citation"), "url": p.get("url"), "evidence": {}}
    for area in p.get("exempt_areas", []):
        if point_in_polygon(lon, lat, area["polygon"]):
            out.update(status="pass", detail=f"Inside the {area['name']}: no parking minimum applies. {p.get('exempt_note', '')}".strip(), citation=area["citation"])
            out["evidence"] = {"exempt_area": area["name"], "required_spaces": 0}
            return out
    ratio = p.get("ratios", {}).get(use)
    if p.get("minimums") is not True or ratio is None:
        out.update(status="unknown", detail=p.get("unverified_uses_note", "Parking rule not verified for this use."))
        return out
    if not gfa_sqft:
        out.update(status="unknown", detail=f"Requires {ratio} spaces per 1,000 sq ft GFA, but the leased floor area is unknown.")
        return out
    required = math.ceil(gfa_sqft / 1000 * ratio)
    provided = math.floor(paved_sqft / SQFT_PER_SPACE) if paved_sqft else 0
    out["evidence"] = {
        "ratio_per_1000_sqft": ratio,
        "gfa_sqft_assumed": round(gfa_sqft),
        "required_spaces": required,
        "paved_area_sqft": round(paved_sqft) if paved_sqft else None,
        "estimated_onsite_spaces": provided,
        "sqft_per_space_assumption": SQFT_PER_SPACE,
    }
    if provided >= required:
        out.update(status="pass", detail=f"Needs ~{required} spaces ({ratio}/1,000 sq ft × {gfa_sqft:,.0f} sq ft); paved area suggests ~{provided} on site.")
    else:
        out.update(
            status="risk",
            detail=(
                f"Needs ~{required} spaces ({ratio}/1,000 sq ft × {gfa_sqft:,.0f} sq ft) but paved area suggests only ~{provided} on site "
                "(shared parking, a parking agreement or a variance may be needed). Not all paving is striped parking."
            ),
        )
    return out


def use_requirements(jur: dict, business_type: str) -> list[dict]:
    use = business(business_type)["zoning_use"]
    reqs = jur.get("requirements", {})
    items = []
    for r in [*reqs.get(use, []), *reqs.get("all", [])]:
        items.append({
            "id": r["id"],
            "rule": r["rule"],
            "status": "risk",  # an action/approval is required; the site's status is unverified
            "detail": r["detail"].strip(),
            "citation": r.get("citation"),
            "url": r.get("url"),
        })
    return items


def flood_item(jur: dict, zone: dict) -> dict:
    """Compliance item for a FEMA flood zone using the jurisdiction's verified flood text."""
    rule = jur.get("flood") or {}
    base = {"id": "flood_zone", "rule": "Flood hazard zone", "citation": rule.get("citation"), "url": rule.get("url"), "evidence": zone}
    if zone.get("status") != "ok":
        return {**base, "status": "unknown", "detail": zone.get("error") or "Flood zone could not be determined; check the FEMA Flood Map Service Center."}
    label = f"FEMA zone {zone.get('zone')}" + (f" ({zone['subtype'].lower()})" if zone.get("subtype") else "")
    if zone.get("sfha"):
        return {**base, "status": "risk", "level": "sfha", "detail": f"{label}. {rule.get('sfha', '').strip()}"}
    if zone.get("moderate"):
        return {**base, "status": "risk", "level": "moderate", "detail": f"{label}. {rule.get('moderate', '').strip()}"}
    return {**base, "status": "pass", "level": "minimal", "detail": f"{label}. {rule.get('minimal', '').strip()}"}
