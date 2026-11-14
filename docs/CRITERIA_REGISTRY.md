# Criteria Registry

`backend/criteria.yaml` (override with `CRITERIA_PATH`) decides what gets checked, how much it
matters, and what happens when data is missing. It is validated by the `Criterion` Pydantic model and
loaded by `backend/app/services/criteria_manager.py`. The file is **re-read automatically when it
changes on disk**, so edits apply on the next request without a restart.

## Fields

| Field | Type / default | Semantics |
|---|---|---|
| `id` | str, unique | Key in `compliance{}`, `criteria_results[]` and `disqualifiers[]`. Duplicates are rejected |
| `description` | str | Shown in the UI |
| `domain` | str | Free-form group (`regulatory`, `safety`, `space`, `health`, `marketing`, ...); the report groups results by domain in registry order |
| `weight` | float >= 0, default 0 | Relative importance. `0` = evaluated and shown, not scored. Weights need not sum to 100 |
| `hard_block` | bool, default false | Disqualify the property when the evaluator reports a **definitive** failure. Missing data never blocks |
| `evaluator` | str | Name registered with `@evaluator("name")` in `services/evaluators.py`. Unknown name → UNKNOWN result, no crash |
| `required_inputs` | list[str] | Input names that must be present (observed facts or requirement values, see below); if any is missing → UNKNOWN and the evaluator is skipped |
| `missing_data_policy` | `assume_risk` (default) \| `assume_cost` \| `unknown` \| `ignore` | What an UNKNOWN means for the score (table below) |
| `evidence_required` | bool, default false | A PASS needs at least one CoStar, Matterport or Vexcel evidence item, else it is downgraded to UNKNOWN |
| `source` | str | Citation shown in the UI (an evaluator may override it with a jurisdiction citation) |
| `thresholds` | map, default {} | Evaluator-specific knobs (table below) |
| `business_types` | list, default `["ALL"]` | Business type ids this applies to |
| `applicable_jurisdictions` | list, default `["ALL"]` | `"ALL"`, a state code (`"TX"`) or a city (`"Austin"`), case-insensitive |

### Missing-data policies

| Policy | Status | Counted in score? | Extra |
|---|---|---|---|
| `assume_risk` | UNKNOWN | yes, as 0 | |
| `assume_cost` | UNKNOWN | yes, as 0 | The evaluator's `fallback` adds the fix cost; an assumption is recorded |
| `unknown` / `ignore` | UNKNOWN | no | Shown only |

The same policy applies when an evaluator itself returns UNKNOWN (e.g. zoning district not in the table),
**except a "verify" UNKNOWN**: when an evaluator sets `EvalOutcome.verify=True` (the data exists but only
the landlord can settle it), the result is excluded from the score whatever the policy, with no cost.
Today only `hvac_checker` does this, for a short prorated share of building-level HVAC.

### Thresholds in use

| Criterion | Threshold | Default | Meaning |
|---|---|---|---|
| `parking_sufficiency` | `min_ratio` | 1.0 | Counted / required spaces needed for PASS |
| `parking_sufficiency` | `sqft_per_space` | 350 | Paved sq ft per space when estimating from Vexcel `paved_area_sqft` (no estimate below one space). Read by the Vexcel provider too |
| `ada_accessibility` | `min_width` | 32 | Door clear width, inches |
| `hvac_capacity` | `tons_per_unit` | 5 | Tons per rooftop unit; turns Vexcel unit counts into tons and sizes `hvac_rtu` |
| `hvac_capacity` | `prorate_by_footprint` | true | Evaluate the suite's share `hvac_tons × min(1, size_sqft / building_footprint_sqft)` when the footprint is known and larger than the listing; a short share is "verify with landlord" |
| `window_visibility` | `min_area` | 10 | Street-facing glass, sq ft |
| `roof_condition` | `min_condition` | 3 | Vexcel roof score (1-5) needed for PASS |
| `roof_condition` | `serious_defects` (optional, not set) | `[structural-damage, tarp]` | Defects that are a RISK whatever the score |

### Available input names

Observed facts: listing (`zoning_code`, `previous_use`, `size_sqft`, `use_restrictions`); Matterport
(`door_width_inches`, `step_free_entrance`, `kitchen_equipment_visible`, `hood_present`,
`grease_interceptor_present`, `bathrooms_visible`, `plumbed_operatories`, `electrical_service_amps`,
`sprinklered`, `window_area`); Vexcel (`visible_parking_count` from fixtures, plus the live/snapshot facts
`rooftop_hvac_units`, `hvac_tons`, `paved_area_sqft`, `estimated_parking_spaces`, `vehicles_count`,
`roof_condition`, `roof_material`, `roof_defects`, `building_footprint_sqft`, `building_footprint`,
`building_type`); plus any new key you add to `fixtures/observations.json`.
Derived values: `business_required_parking` (per property: the city minimum for its size and location,
never below the user's number), `code_required_parking`, `parking_requirement_note`,
`business_required_bathrooms`, `business_capacity`, `required_hvac_tons`, `required_electrical_amps`,
`occupant_load`, `needs_kitchen`, `size_sqft`, `monthly_rent` (see `compliance_engine.build_inputs`).

## Scoring (`services/scoring.py`)

```
score = 100 × Σ(weight × criterion_score) / Σ(weight)     over counted criteria only
criterion_score: PASS = 1, RISK = 0, counted UNKNOWN = 0
```

The denominator is the counted weight, so adding a criterion re-normalizes automatically.
Example: 801 St Emanuel (Houston demo) passes zoning (10), parking (10), ADA (15), restrooms (10),
electrical (5), window (5) and roof (5) and fails kitchen (20) and grease interceptor (10): 60 of 90
counted weight → **66.7**. HVAC (10) is a "verify" UNKNOWN and fire safety has weight 0, so neither is
counted. The score orders results only through the weak-fit gate (`ranking.min_score` in
`costs.yaml`) and tie-breaks; see [COST_ENGINE.md](COST_ENGINE.md#ranking).

## Current registry

| id | domain | weight | hard_block | evaluator | policy | evidence_required | applies to |
|---|---|---|---|---|---|---|---|
| `zoning_use` | regulatory | 10 | yes | `zoning_checker` | unknown | yes | ALL |
| `parking_sufficiency` | regulatory | 10 | no | `parking_checker` | assume_risk | yes | ALL |
| `ada_accessibility` | safety | 15 | no | `ada_checker` | assume_risk | yes | ALL |
| `kitchen_equipment` | space | 20 | no | `kitchen_checker` | assume_cost | no | restaurant |
| `grease_interceptor` | health | 10 | no | `grease_checker` | assume_cost | no | restaurant |
| `operatory_plumbing` | space | 20 | no | `operatory_checker` | assume_cost | no | dental_clinic |
| `bathroom_count` | safety | 10 | no | `bathroom_checker` | assume_risk | yes | ALL |
| `hvac_capacity` | space | 10 | no | `hvac_checker` | assume_risk | yes | ALL |
| `electrical_service` | space | 5 | no | `electrical_checker` | assume_risk | yes | ALL |
| `fire_safety` | safety | 0 | yes | `fire_safety_checker` | unknown | no | ALL |
| `window_visibility` | marketing | 5 | no | `check_window_visibility` | ignore | no | restaurant |
| `roof_condition` | space | 5 | no | `roof_checker` | unknown | yes | ALL |

All entries use `applicable_jurisdictions: ["ALL"]`. A restaurant gets 11 criteria, a dental clinic 9.

Notes on specific entries:
- `zoning_use` has `required_inputs: []` on purpose: a no-zoning city (`zoning_mode: none`, Houston)
  has no zoning code to require. The evaluator reports a missing code as UNKNOWN itself, and the
  citation comes from the jurisdiction's `zoning_source`. It also hard-blocks on a disclosed use
  restriction that prohibits the use.
- `parking_sufficiency` requires only `business_required_parking`; the space count is
  `visible_parking_count`, else Vexcel `estimated_parking_spaces`, else UNKNOWN (counted as 0 under
  `assume_risk`). Its `source` is replaced by the jurisdiction's parking citation.
- `hvac_capacity` keeps `assume_risk` for truly missing data, but a short prorated share is a "verify"
  UNKNOWN and is not counted.
- `roof_condition` uses Vexcel data only; offline listings without roof data get UNKNOWN, not scored.

## How to add a criterion (config only)

Reuse an existing evaluator with new thresholds or a new scope. Example:

```yaml
- id: "parking_generous"
  description: "Parking covers 1.5x the spaces the business needs"
  domain: "regulatory"
  weight: 5
  hard_block: false
  evaluator: "parking_checker"
  required_inputs: ["business_required_parking"]
  missing_data_policy: "ignore"
  evidence_required: true
  source: "Business preference"
  thresholds: { min_ratio: 1.5 }
  business_types: ["restaurant"]
  applicable_jurisdictions: ["TX"]
```

Save the file and run a new analysis. The criterion appears in `GET /api/v1/criteria`, in the
"Criteria used" table on `/properties`, and in every report. Stored analyses are snapshots and do
not change. A malformed entry returns a 500 whose `detail` names the file, the entry number and the
bad field.

`window_visibility` was added this way (prompts/scale-criteria.md); `roof_condition` reused the same path
with one new evaluator (`roof_checker`) and one cost item (`roof_repair`). Changing a threshold works the
same: setting `roof_condition` `min_condition: 3` → `4` turns three Houston roofs (scored 3/5) into RISK
with a priced roof repair ([DEMO_RUNBOOK.md](DEMO_RUNBOOK.md#5-config-only-scaling-215-245)), and
`tests/test_criteria_manager.py::test_adding_a_criterion_via_config_changes_results` proves it changes
scores with no code change.

## How to add an evaluator (one function)

Needed only when the logic is new. In `backend/app/services/evaluators.py`:

```python
def _signage_fallback(ctx: EvalContext) -> list[CostNeed]:          # optional, used by assume_cost
    return [CostNeed("signage_install", 1, "Signage not confirmed; budgeted")]

@evaluator("signage_checker", fallback=_signage_fallback)
def signage_checker(ctx: EvalContext) -> EvalOutcome:
    has_sign = bool(ctx.value("pylon_sign_present"))                 # a required_input
    if has_sign:
        return EvalOutcome("PASS", "Pylon sign position available.", ctx.evidence("pylon_sign_present"))
    return EvalOutcome(
        "RISK", "No pylon sign position.", ctx.evidence("pylon_sign_present"),
        cost_items=[CostNeed("signage_install", 1, "No sign position")],
        questions=["Can the tenant add a panel to the pylon sign?"],
        definitive_failure=False,   # True only for known failures that should hard-block
    )
```

Then:

1. Reference `evaluator: "signage_checker"` from a `criteria.yaml` entry.
2. If it emits cost items, add `signage_install` to `config/costs.yaml` `items`.
3. If it needs a new observed fact, add it to `fixtures/observations.json` (and to the live
   provider mapping later). Optionally add a friendly label to `INPUT_LABELS` in `compliance_engine.py`.

`EvalContext` gives you `requirements`, `property`, `observations`, `criterion`, `thresholds`,
`jurisdiction`, `business`, `value(name)`, `evidence(*keys)` and `derived(key, value, note, source)`.
`EvalOutcome` also takes `source=` (override the citation) and `verify=True` (an UNKNOWN that is
excluded from the score; use it when the data exists but only the landlord can confirm it).
`tests/test_evaluators.py::test_every_criteria_yaml_evaluator_is_registered` fails if the YAML
names an evaluator that does not exist.

## Adding a business type

Add a block to `config/business_types.yaml` (label, capacity unit, occupancy group, zoning use,
occupant load factors, parking guideline, restroom rule, HVAC sq ft/ton, amps, build-out months,
optional sprinkler trigger). It appears in the form via `GET /api/v1/business-types`. Add
`zoning.<zoning_use>` lists to `jurisdictions.yaml` so zoning can be checked, and scope
type-specific criteria with `business_types: [<id>]`. For a city with parking minimums, add the
type's `zoning_use` to that city's `parking_ratios`.
