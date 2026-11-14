"""Requirements parser agent: free-text business details -> structured `Requirements`.

Two extractors produce the same raw fields (capacity, bathrooms, parking, sq ft range, max rent,
kitchen need):

* **regex** — always available, deterministic, offline.
* **claude** — used first when ANTHROPIC_API_KEY is set. Its JSON is validated and merged over the
  regex result. Any error, refusal or timeout falls back to regex silently (logged).

Everything the user did not state is filled from backend/config/business_types.yaml, and every
default is recorded as a human-readable string in `Requirements.assumptions`.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from ..config import business_types, jurisdiction_for, log, settings
from ..models import BusinessProfile, Property, Requirements

CLAUDE_TIMEOUT_SECONDS = 8.0
RAW_FIELDS = ("capacity", "bathrooms", "parking", "min_sqft", "max_sqft", "max_rent", "needs_kitchen")


class UnknownBusinessType(ValueError):
    """Raised when the profile's business type is not in business_types.yaml (-> HTTP 400)."""


# --------------------------------------------------------------------------------------------
# Regex extractor
# --------------------------------------------------------------------------------------------

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "a single": 1, "single": 1,
}
_NUM = r"(\d[\d,]*(?:\.\d+)?)\s*(k)?"  # "5,000", "5k", "2.5k"
_SQFT_UNIT = r"(?:sq\.?\s*ft\.?|sqft|sf|square\s*feet|square\s*foot|ft2)"
_CAPACITY_WORDS = (
    r"seats?|seating|covers|diners|guests|chairs?|operator(?:y|ies)|ops|treatment\s*rooms?|"
    r"exam\s*rooms?|stations?|tables?|people|persons|customers"
)
_BATHROOM_WORDS = r"bath(?:room)?s?|restrooms?|toilets?|washrooms?|lavatories|lavatory|wcs?"
_PARKING_WORDS = r"(?:parking\s*)?(?:spaces?|spots?|stalls?)|parking"


def _to_number(digits: str, k_suffix: str | None = None) -> float:
    value = float(digits.replace(",", ""))
    return value * 1000 if k_suffix else value


def _normalize(text: str) -> str:
    out = f" {text.lower()} "
    for word, num in sorted(_NUMBER_WORDS.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"\b{word}\b", str(num), out)
    return out


def regex_extract(details: str) -> dict[str, Any]:
    """Extract raw requirement fields from free text. Missing fields are absent from the dict."""
    text = _normalize(details or "")
    found: dict[str, Any] = {}

    # Capacity: "40 seats", "40-seat", "4 chairs", "seating for 40".
    m = re.search(rf"(\d+)\s*-?\s*(?:{_CAPACITY_WORDS})\b", text) or re.search(
        r"\b(?:seating|seats?|capacity|room)\s*(?:for|of)?\s*(\d+)", text
    )
    if m:
        found["capacity"] = int(m.group(1))

    m = re.search(rf"(\d+)\s*-?\s*(?:{_BATHROOM_WORDS})\b", text)
    if m:
        found["bathrooms"] = int(m.group(1))

    # Parking: "20 parking spaces", "20 spots", "parking for 20".
    m = re.search(rf"(\d+)\s*-?\s*(?:{_PARKING_WORDS})\b", text) or re.search(
        r"parking\s*(?:for|of|:)?\s*(\d+)", text
    )
    if m:
        found["parking"] = int(m.group(1))
    if re.search(r"\bno\s+parking\b", text):
        found["parking"] = 0

    # Square footage: ranges first, then bounds, then a single target.
    m = re.search(rf"{_NUM}\s*(?:-|–|to)\s*{_NUM}\s*{_SQFT_UNIT}", text)
    if m:
        found["min_sqft"] = int(_to_number(m.group(1), m.group(2)))
        found["max_sqft"] = int(_to_number(m.group(3), m.group(4)))
    else:
        lower = re.search(rf"(?:at\s*least|min(?:imum)?|over|more\s*than|>=?)\s*{_NUM}\s*{_SQFT_UNIT}", text)
        upper = re.search(rf"(?:up\s*to|at\s*most|max(?:imum)?|under|less\s*than|below|<=?)\s*{_NUM}\s*{_SQFT_UNIT}", text)
        if lower:
            found["min_sqft"] = int(_to_number(lower.group(1), lower.group(2)))
        if upper:
            found["max_sqft"] = int(_to_number(upper.group(1), upper.group(2)))
        if not lower and not upper:
            single = re.search(rf"{_NUM}\s*{_SQFT_UNIT}", text)
            if single:
                # "about 2000 sq ft" -> accept roughly +/-20%.
                target = _to_number(single.group(1), single.group(2))
                found["min_sqft"] = int(round(target * 0.8))
                found["max_sqft"] = int(round(target * 1.2))

    # Max rent / budget: "$5,000/month", "budget 5k", "rent under $5000", "max rent 4500".
    not_area = rf"(?!\s*{_SQFT_UNIT})"
    m = re.search(rf"(?:budget|rent)[^\d$]{{0,20}}\$?\s*{_NUM}{not_area}", text) or re.search(
        rf"\$\s*{_NUM}{not_area}", text
    )
    if m:
        found["max_rent"] = _to_number(m.group(1), m.group(2))

    if re.search(r"\b(?:no|without|don'?t\s+need\s+(?:a\s+)?)\s*(?:commercial\s+)?kitchen\b", text):
        found["needs_kitchen"] = False
    elif re.search(r"\bkitchen\b", text):
        found["needs_kitchen"] = True

    return found


# --------------------------------------------------------------------------------------------
# Claude extractor (optional)
# --------------------------------------------------------------------------------------------

_NULLABLE_INT = {"type": ["integer", "null"]}
CLAUDE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "capacity": {**_NULLABLE_INT, "description": "Seats / chairs / treatment rooms the business needs"},
        "bathrooms": {**_NULLABLE_INT, "description": "Restrooms required"},
        "parking": {**_NULLABLE_INT, "description": "Parking spaces required"},
        "min_sqft": {**_NULLABLE_INT, "description": "Minimum square feet"},
        "max_sqft": {**_NULLABLE_INT, "description": "Maximum square feet"},
        "max_rent": {"type": ["number", "null"], "description": "Maximum monthly rent in USD"},
        "needs_kitchen": {"type": ["boolean", "null"], "description": "Whether a commercial kitchen is needed"},
    },
    "required": list(RAW_FIELDS),
    "additionalProperties": False,
}

_CLAUDE_SYSTEM = (
    "You extract structured space requirements from a small-business owner's description of the "
    "commercial space they need. Return only values the text states or clearly implies; use null "
    "for anything not mentioned. Do not guess defaults."
)


def _anthropic_client():
    """Build the SDK client. Separate function so tests can replace it with a fake."""
    import anthropic

    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key, timeout=CLAUDE_TIMEOUT_SECONDS, max_retries=0
    )


def _validate_claude_fields(data: Any) -> dict[str, Any]:
    """Keep only well-typed, plausible values; drop the rest (regex/defaults fill them)."""
    if not isinstance(data, dict):
        raise ValueError("Claude output is not a JSON object")
    clean: dict[str, Any] = {}
    limits = {"capacity": 2000, "bathrooms": 50, "parking": 2000, "min_sqft": 500_000, "max_sqft": 500_000}
    for key, upper in limits.items():
        value = data.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)) and 0 <= value <= upper:
            clean[key] = int(value)
    rent = data.get("max_rent")
    if isinstance(rent, (int, float)) and not isinstance(rent, bool) and 0 < rent <= 10_000_000:
        clean["max_rent"] = float(rent)
    if isinstance(data.get("needs_kitchen"), bool):
        clean["needs_kitchen"] = data["needs_kitchen"]
    if "min_sqft" in clean and "max_sqft" in clean and clean["min_sqft"] > clean["max_sqft"]:
        clean.pop("min_sqft"), clean.pop("max_sqft")
    return clean


def claude_extract(details: str, business_label: str) -> dict[str, Any]:
    """Ask Claude for the raw fields as schema-constrained JSON. Raises on any failure."""
    client = _anthropic_client()
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=2048,
        system=_CLAUDE_SYSTEM,
        messages=[{"role": "user", "content": f"Business type: {business_label}\nDescription: {details}"}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": CLAUDE_SCHEMA}},
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"Claude stopped with stop_reason={response.stop_reason}")
    text = next(block.text for block in response.content if block.type == "text")
    return _validate_claude_fields(json.loads(text))


# --------------------------------------------------------------------------------------------
# Defaults + assembly
# --------------------------------------------------------------------------------------------


def get_business(business_type: str) -> dict:
    types = business_types()
    if business_type not in types:
        raise UnknownBusinessType(
            f"Unknown business type '{business_type}'. Known types: {', '.join(sorted(types))}"
        )
    return types[business_type]


def occupant_load(business: dict, capacity: int) -> int:
    staff = business.get("staff", {})
    load = (
        capacity * business.get("occupants_per_capacity_unit", 1)
        + staff.get("base", 0)
        + staff.get("per_capacity_unit", 0) * capacity
    )
    return int(math.ceil(load))


def restrooms_for(business: dict, load: int) -> int:
    """Simplified fixture rule: one single-user room for small loads, else separate facilities per sex."""
    rule = business.get("restrooms", {})
    if load <= rule.get("single_user_max_occupants", 15):
        return 1
    per_sex = math.ceil((load / 2) / rule.get("occupants_per_fixture_per_sex", 75))
    return 2 * max(per_sex, 1)


# --------------------------------------------------------------------------------------------
# Parking: jurisdiction minimums (config/jurisdictions.yaml)
# --------------------------------------------------------------------------------------------


@dataclass
class ParkingMinimum:
    """A city's off-street parking minimum for one use at one size / location.

    spaces is None when the city sets no minimum for this use (then the business need applies);
    0 inside an exempt area (e.g. Houston's market-based parking areas)."""

    spaces: int | None
    ratio: float | None = None  # spaces per 1,000 sq ft GFA
    exempt_area: str | None = None
    source: str | None = None
    note: str = ""


def _point_in_polygon(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray casting; `ring` is [[lon, lat], ...] (closing point optional)."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def exempt_parking_area(jurisdiction: dict, latitude: float | None, longitude: float | None) -> dict | None:
    """The jurisdiction's parking-exempt area containing this point, if any."""
    if latitude is None or longitude is None:
        return None
    for area in jurisdiction.get("parking_exempt_areas") or []:
        if area.get("polygon") and _point_in_polygon(longitude, latitude, area["polygon"]):
            return area
    return None


def code_parking_minimum(
    jurisdiction: dict, use: str, sqft: float, latitude: float | None = None, longitude: float | None = None
) -> ParkingMinimum:
    """Spaces the city requires for `use` (business_types.yaml `zoning_use`) at `sqft` GFA.

    Config-driven: `parking_minimums`, `parking_ratios`, `parking_exempt_areas` in jurisdictions.yaml.
    Without a location the city-wide ratio is used (exempt areas can't be checked)."""
    ratio = (jurisdiction.get("parking_ratios") or {}).get(use)
    name = jurisdiction.get("name", "This city")
    if not jurisdiction.get("parking_minimums") or ratio is None:
        return ParkingMinimum(spaces=None)
    area = exempt_parking_area(jurisdiction, latitude, longitude)
    if area:
        return ParkingMinimum(
            spaces=0, ratio=float(ratio), exempt_area=area.get("name"),
            source=area.get("source") or jurisdiction.get("parking_ratio_source"),
            note=f"In the {area.get('name')}: {name} sets no parking minimum here.",
        )
    spaces = int(math.ceil(float(ratio) * sqft / 1000))
    source = jurisdiction.get("parking_ratio_source")
    return ParkingMinimum(
        spaces=spaces, ratio=float(ratio), source=source,
        note=f"{name} code minimum: {float(ratio):g} spaces per 1,000 sq ft x {sqft:,.0f} sq ft = {spaces} spaces"
        + (f" ({source})." if source else "."),
    )


def property_parking_requirement(
    requirements: Requirements, prop: Property, jurisdiction: dict, business: dict
) -> tuple[int, ParkingMinimum]:
    """Spaces this specific property must provide: the city minimum for its actual size and location
    (market-based / exempt areas -> 0), never below what the user said they need."""
    use = business.get("zoning_use", requirements.business_type)
    rule = code_parking_minimum(jurisdiction, use, prop.size_sqft, prop.latitude, prop.longitude)
    if rule.spaces is None:
        return requirements.parking_required, rule
    if requirements.parking_source == "jurisdiction":
        return rule.spaces, rule
    return max(requirements.parking_required, rule.spaces), rule


def build_requirements(profile: BusinessProfile, raw: dict[str, Any]) -> Requirements:
    """Turn raw extracted fields into full Requirements, filling defaults as recorded assumptions."""
    business = get_business(profile.type)
    unit = business.get("capacity_unit", "units")
    assumptions: list[str] = []

    capacity = raw.get("capacity")
    if not capacity:
        capacity = int(business.get("default_capacity", 1))
        assumptions.append(f"Capacity not stated; assumed {capacity} {unit} (typical {business['label'].lower()}).")

    load = occupant_load(business, capacity)
    assumptions.append(
        f"Occupant load {load} = {capacity} {unit} x {business.get('occupants_per_capacity_unit', 1)} + staff."
    )

    # Space need is needed early for the city parking minimum; its assumption is recorded below.
    min_sqft, max_sqft = raw.get("min_sqft"), raw.get("max_sqft")
    sqft_need = min_sqft or int(capacity * business.get("sqft_per_capacity_unit", 0))

    jurisdiction = jurisdiction_for(profile.city, profile.state)
    code = code_parking_minimum(jurisdiction, business.get("zoning_use", profile.type), sqft_need)
    city = jurisdiction.get("name", profile.city)
    if raw.get("parking") is not None:
        parking, parking_source = int(raw["parking"]), "user"
        if code.spaces is not None:
            assumptions.append(
                f"{city} also sets a parking minimum ({code.ratio:g} spaces per 1,000 sq ft GFA, {code.source}); "
                "each property is checked against the larger of that minimum and your number "
                "(no minimum in market-based parking areas)."
            )
    elif code.spaces is not None:
        parking, parking_source = code.spaces, "jurisdiction"
        assumptions.append(
            f"Parking not stated; using the {city} code minimum of {code.ratio:g} spaces per 1,000 sq ft GFA "
            f"x {sqft_need} sq ft = {parking} spaces ({code.source}). Recomputed for each property's size; "
            "no minimum in market-based parking areas."
        )
    else:
        ratio = business.get("parking_per_capacity_unit", 0)
        parking, parking_source = int(math.ceil(capacity * ratio)), "guideline"
        assumptions.append(
            f"Parking not stated; using a business guideline of {ratio} spaces per {unit[:-1] if unit.endswith('s') else unit}"
            f" = {parking} spaces (not a code minimum)."
        )

    if raw.get("bathrooms"):
        bathrooms = int(raw["bathrooms"])
    else:
        bathrooms = restrooms_for(business, load)
        assumptions.append(f"Restrooms not stated; {bathrooms} required for an occupant load of {load} (simplified fixture table).")

    needs_kitchen = raw.get("needs_kitchen")
    if needs_kitchen is None:
        needs_kitchen = bool(business.get("needs_kitchen", False))
        if needs_kitchen:
            assumptions.append(f"Assumed a commercial kitchen is needed (typical for a {business['label'].lower()}).")

    if not min_sqft:
        assumptions.append(
            f"Space need estimated at {sqft_need} sq ft ({business.get('sqft_per_capacity_unit')} sq ft per {unit[:-1] if unit.endswith('s') else unit})."
        )

    per_ton = business.get("hvac_sqft_per_ton", 250)
    hvac_tons = round(sqft_need / per_ton, 1)
    assumptions.append(f"HVAC need {hvac_tons} tons at {per_ton} sq ft per ton (rule of thumb).")

    amps = int(business.get("electrical_amps", 200))
    assumptions.append(f"Electrical service of {amps} A assumed typical for a {business['label'].lower()}.")

    return Requirements(
        business_type=profile.type,
        business_label=business["label"],
        city=profile.city.strip(),
        state=profile.state.strip().upper(),
        capacity=capacity,
        capacity_unit=unit,
        occupant_load=load,
        parking_required=parking,
        parking_source=parking_source,
        bathrooms_required=bathrooms,
        min_sqft=min_sqft,
        max_sqft=max_sqft,
        max_rent=raw.get("max_rent"),
        needs_kitchen=needs_kitchen,
        required_hvac_tons=hvac_tons,
        required_electrical_amps=amps,
        assumptions=assumptions,
    )


def parse_requirements(profile: BusinessProfile) -> tuple[Requirements, str]:
    """Run the parser agent. Returns (requirements, parser_used) where parser_used is 'regex' | 'claude'."""
    business = get_business(profile.type)  # validate before spending an API call
    raw = regex_extract(profile.details)
    parser_used = "regex"
    if settings.anthropic_api_key and profile.details.strip():
        try:
            claude_fields = claude_extract(profile.details, business["label"])
            raw = {**raw, **claude_fields}
            parser_used = "claude"
        except Exception as exc:  # noqa: BLE001 - any Claude failure falls back to regex
            log.warning("Claude requirements parsing failed (%s: %s); using regex", type(exc).__name__, exc)
    return build_requirements(profile, raw), parser_used
