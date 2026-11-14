# Data Models

Pydantic v2 models live in `backend/app/models/`, the SQLite table in `backend/app/db.py`. The
frontend mirror is `frontend/lib/types.ts`. The wire format is defined in
[API_CONTRACT.md](API_CONTRACT.md); this page explains where each model comes from.

## Input

### `BusinessProfile` (`business_profile.py`)
What the user typed.

| Field | Type | Notes |
|---|---|---|
| `type` | `str` (min 1) | Must be a key of `config/business_types.yaml` (`restaurant`, `dental_clinic`), else 400 |
| `details` | `str` = `""` | Free text, e.g. `"40 seats, kitchen needed, 2 bathrooms, 20 parking spaces"` |
| `city` | `str` (min 1) | City name |
| `state` | `str` (min 2) | State code |

### `AnalyzeRequest` (`analysis_result.py`)
`business_profile: BusinessProfile`, `property_ids: list[str]` (min length 1).

## Derived

### `Requirements` (`business_profile.py`)
Output of the requirements parser agent. Anything the user did not state is filled from the business
profile and recorded in `assumptions`.

| Field | Meaning |
|---|---|
| `business_type`, `business_label`, `city`, `state` | Echo of the profile (`state` upper-cased) |
| `capacity`, `capacity_unit` | e.g. 40 `seats`, 4 `chairs` (default `default_capacity`) |
| `occupant_load` | `ceil(capacity × occupants_per_capacity_unit + staff.base + staff.per_capacity_unit × capacity)` |
| `parking_required`, `parking_source` | Stated value (`"user"`) or `ceil(capacity × parking_per_capacity_unit)` (`"guideline"`) |
| `bathrooms_required` | Stated, or a simplified fixture rule from occupant load |
| `min_sqft`, `max_sqft`, `max_rent` | Parsed if stated, else `null` |
| `needs_kitchen` | Stated ("kitchen needed" / "no kitchen") or the business default |
| `required_hvac_tons` | Space need (`min_sqft` or `capacity × sqft_per_capacity_unit`) ÷ `hvac_sqft_per_ton` |
| `required_electrical_amps` | `electrical_amps` from the business profile |
| `assumptions` | Human-readable list of every default applied |

### `Property` (`property.py`)
A CoStar listing: `id, address, city, state, zip, size_sqft, rent` (monthly), optional `zoning,
previous_use, ti_allowance_per_sqft, latitude, longitude, image_url, matterport_url`, `available`
(default true).

### `Criterion` (`criterion.py`)
One entry of `criteria.yaml`: `id, description, domain, weight (>= 0), hard_block, evaluator,
required_inputs, missing_data_policy ("assume_risk" | "assume_cost" | "unknown" | "ignore"),
evidence_required, source, thresholds (null becomes {}), business_types (default ["ALL"]),
applicable_jurisdictions (default ["ALL"])`. Field semantics: [CRITERIA_REGISTRY.md](CRITERIA_REGISTRY.md).

### `Evidence`
One observed or derived fact: `key, value, source ("costar" | "matterport" | "vexcel" |
"requirements" | "jurisdiction"), note, confidence (0-1), box ([x, y, w, h] normalized)`.
`OBSERVED_SOURCES = {costar, matterport, vexcel}`: only these satisfy `evidence_required`.

## Output

### `AnalyzeResponse`
`analysis_id` (uuid4 hex), `created_at` (ISO-8601 UTC, ms, `Z`), `business_type`, `requirements`,
`ranking_basis` (sentence), `min_score` (the `ranking.min_score` threshold used), `results`
(sorted by rank), `mode` (`costar/matterport/vexcel: mock|live`, `parser`: the parser actually
used), `disclaimer` (from `costs.yaml`).

### `AnalysisResult` (one per property)

| Field | Source |
|---|---|
| `property_id`, `address`, `monthly_rent` | Listing |
| `rank` | `rank_results` (1 = best) |
| `score` | `weighted_score` over counted criteria, 0-100 |
| `weak_fit` | `score < min_score` (and not disqualified): ranked after qualifying spaces |
| `disqualified`, `disqualifiers` | Criterion ids whose result is `blocking` |
| `fit_out_estimate` | Gross fit-out (sum of all `line_items`) |
| `ti_allowance` | `ti_allowance_per_sqft × size_sqft` |
| `total_cost_estimate` | Cost to open = net fit-out + rent × build-out months |
| `first_year_cost` | Cost to open + `horizon_months` × rent |
| `buildout_months` | `CostRange` in months |
| `line_items` | `CostLineItem {item, label, qty, min, max, reason}`: hard items, then general conditions, contingency, permits |
| `breakdown` | `{item id: CostRange}` for the same line items |
| `compliance` | `{criterion id: ComplianceStatus {status, notes, source}}` |
| `criteria_results` | `CriterionResult[]` (below) |
| `questions_for_landlord`, `landlord_request` | Recommendation agent |
| `observations` | `{fact: Evidence}` from CoStar / Matterport / Vexcel |
| `media` | `Media {aerial_url, floor_plan_url, matterport_embed_url, image_url}` |
| `assumptions` | Policy, cost, jurisdiction and low-confidence notes |

### `CriterionResult`
`id, description, domain, weight, status, score (1 PASS / 0 RISK or counted UNKNOWN / null when not
counted), counted, hard_block, blocking, notes, source, evidence[]`.

### `AnalysisSummary`
One row of `GET /api/v1/analyses`: `analysis_id, created_at, business_type, business_label, city,
state, property_count, top_property_id, top_address`.

## SQLite: `analysis_runs` (`db.py`, SQLModel `AnalysisRun`)

| Column | Type | Notes |
|---|---|---|
| `id` | `str` PK (max 32) | `analysis_id` |
| `created_at` | `str`, indexed | Same string as the response |
| `business_type`, `business_label`, `city`, `state` | `str` | For the history list |
| `property_count` | `int` | |
| `top_property_id`, `top_address` | `str?` | Rank-1 result |
| `response_json` | `TEXT` not null | Full `AnalyzeResponse` JSON; `GET /analyses/{id}` returns it, filling defaults for fields added since (e.g. `min_score: 0`, `weak_fit: false`) |

Database URL: `DATABASE_URL` (default `sqlite:///./turnkey.db`, resolved relative to `backend/`).
The table is created on startup (`init_db`). There are no migrations: if a schema change ever
matters, delete `backend/turnkey.db`.

## Internal (not on the wire)

- `EvalContext` / `EvalOutcome` / `CostNeed` (`services/evaluators.py`): evaluator inputs and outputs.
- `ComplianceReport` (`services/compliance_engine.py`): results, cost needs, questions,
  assumptions, disqualifiers, plus `score`.
- `CostEstimate` (`services/cost_engine.py`): line items, hard costs, fit-out, TI, net fit-out,
  build-out months, cost to open, first-year cost, horizon.
