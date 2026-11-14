# Compliance Agent

The compliance / criteria agent (`backend/app/services/compliance_engine.py`) runs every applicable
criterion from `backend/criteria.yaml` against one property. It returns PASS / RISK / UNKNOWN with
a plain-English note, a source citation and the evidence behind it. It flags issues for follow-up
and does **not** certify legality.

## Statuses

| Status | Meaning | UI color |
|---|---|---|
| `PASS` | Evidence shows the requirement is met | green (`--color-pass`) |
| `RISK` | Evidence shows a shortfall, or a known failure (costed when fixable) | orange (`--color-risk`) |
| `UNKNOWN` | Not enough data, no rule loaded, or the evaluator failed | gray (`--color-unknown`) |

## How a criterion is evaluated (`evaluate_criterion`)

1. **Evaluator lookup.** If the `evaluator` name is not registered → UNKNOWN ("No evaluator named ... is registered").
2. **Required inputs.** If any `required_inputs` value is missing → UNKNOWN ("Not enough data: could not
   confirm ..."), plus a landlord question. The evaluator is not called. Under `assume_cost` the
   evaluator's `fallback` prices the fix anyway ("Fix cost included as a precaution").
3. **Evaluator call.** If the function raises → UNKNOWN ("Evaluator ... failed"), and the run continues.
4. **`evidence_required`.** A PASS with no evidence from CoStar, Matterport or Vexcel is downgraded
   to UNKNOWN. Requirement or jurisdiction evidence does not count.
5. **Scoring.** Weight 0 → shown, not counted. PASS = 1, RISK = 0. UNKNOWN is counted as 0 under
   `assume_risk` / `assume_cost` and excluded under `unknown` / `ignore`.
6. **Hard block.** `blocking = hard_block and status == RISK and outcome.definitive_failure and not a data gap`.
   Missing data never disqualifies.

## Evaluators (`backend/app/services/evaluators.py`)

| Evaluator | Criterion (weight) | Logic | Fix cost items |
|---|---|---|---|
| `zoning_checker` | `zoning_use` (10, **hard block**) | Base district (suffixes like `-MU`, `-V` stripped) looked up in the jurisdiction's use table: permitted → PASS; conditional → RISK (CUP needed); prohibited → RISK + **definitive failure**; not listed or no table → UNKNOWN | none |
| `parking_checker` | `parking_sufficiency` (10) | `visible / required >= min_ratio` (1.0) → PASS, else RISK. Required is the user's number or the business guideline; the Austin note says there is no city minimum | none |
| `ada_checker` | `ada_accessibility` (15) | Door `< min_width` (32 in.) or a stepped entrance → RISK | `door_widening`, `entrance_ramp` |
| `kitchen_checker` | `kitchen_equipment` (20, restaurant) | No kitchen needed → PASS; no equipment → RISK; equipment without a hood → RISK; hood unconfirmed → PASS + question | `kitchen_install` / `hood_exhaust`; fallback `kitchen_install` |
| `grease_checker` | `grease_interceptor` (10, restaurant) | Present → PASS, else RISK | `grease_interceptor`; fallback same |
| `operatory_checker` | `operatory_plumbing` (20, dental_clinic) | Plumbed rooms `>=` chairs → PASS, else RISK for the shortfall | `operatory_plumbing` × shortfall; fallback × capacity |
| `bathroom_checker` | `bathroom_count` (10) | Visible `>=` required → PASS, else RISK; cites the jurisdiction plumbing code | `restroom_add` × shortfall |
| `hvac_checker` | `hvac_capacity` (10) | Need = **max**(parsed need, `size_sqft / hvac_sqft_per_ton`); have `>=` need → PASS, else RISK | `hvac_rtu` × ceil(shortfall / 5 tons); fallback sized from need |
| `electrical_checker` | `electrical_service` (5) | Service amps `>=` business amps → PASS, else RISK | `electrical_service_upgrade`; fallback same |
| `fire_safety_checker` | `fire_safety` (0, hard block) | IBC §903.2 trigger from `sprinkler_required_if` (restaurant: > 5,000 sq ft or >= 100 occupants). Not triggered → PASS; triggered and sprinklered → PASS; triggered and not sprinklered → RISK **priced as a retrofit, never definitive**; unconfirmed → UNKNOWN | `fire_sprinkler` × sq ft |
| `check_window_visibility` | `window_visibility` (5, restaurant) | `window_area >= min_area` (10 sq ft) → PASS, else RISK; no data → ignored (not scored) | none |

Because `fire_safety` is never a definitive failure, **zoning is currently the only criterion that can
disqualify a space** in practice.

## Jurisdiction rules (`backend/config/jurisdictions.yaml`)

`config.jurisdiction_for(city, state)` looks up `"<city>-<state>"` (lowercase, spaces → `-`) and
merges it over `default`.

| Key | Used by | Austin, TX | Default |
|---|---|---|---|
| `zoning`, `zoning_source` | `zoning_checker` | Use table for `restaurant` and `medical_office` (LDC §25-2-491, simplified) | empty → zoning UNKNOWN |
| `parking_note` | `parking_checker` | Parking minimums eliminated Nov 2, 2023 | "No local parking rule loaded" |
| `plumbing_code` | `bathroom_checker` | 2024 UPC as amended by Austin, Table 422.1 | IPC Table 2902.1 / UPC Table 422.1 |
| `name` | notes | "Austin, TX" | "Generic (model codes)" |

`building_code`, `health_code` and `parking_minimums` are recorded in the YAML for reference but are
not read by any evaluator yet. A city without an entry adds the assumption "No local rules loaded
for {city}, {state}; model codes used."

Austin zoning table: restaurant permitted in GR, CS, CS-1, CH, CBD, DMU; conditional in LR;
prohibited in LO, GO, NO, SF-1..3, MF-1..3. Medical office is permitted in LO, GO, GR, CS, CS-1, CH,
CBD, DMU; conditional in LR, NO.

## Outputs per property

- `criteria_results[]` and `compliance{id: {status, notes, source}}`
- Cost needs, which feed the [cost engine](COST_ENGINE.md)
- Landlord questions, de-duplicated
- `disqualifiers[]` (blocking criterion ids)
- Assumptions (e.g. "Grease interceptor ...: not confirmed, so the fix is budgeted (assume_cost).")

Demo results (restaurant, Austin): property-456 passes all 10 criteria; property-789 is RISK on
zoning (LO prohibits restaurant) and disqualified; property-321 is RISK on zoning (LR-V →
conditional) but not disqualified.

Citations: [COMPLIANCE_RULE_SOURCES.md](COMPLIANCE_RULE_SOURCES.md).
