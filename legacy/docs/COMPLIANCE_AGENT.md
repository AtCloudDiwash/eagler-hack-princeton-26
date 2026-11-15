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
| `UNKNOWN` | Not enough data, no rule loaded, the evaluator failed, or a **verify with landlord** finding | gray (`--color-unknown`) |

## How a criterion is evaluated (`evaluate_criterion`)

1. **Evaluator lookup.** If the `evaluator` name is not registered → UNKNOWN ("No evaluator named ... is registered").
2. **Required inputs.** If any `required_inputs` value is missing → UNKNOWN ("Not enough data: could not
   confirm ..."), plus a landlord question. The evaluator is not called. Under `assume_cost` the
   evaluator's `fallback` prices the fix anyway ("Fix cost included as a precaution").
3. **Evaluator call.** If the function raises → UNKNOWN ("Evaluator ... failed"), and the run continues.
4. **`evidence_required`.** A PASS with no evidence from CoStar, Matterport or Vexcel is downgraded
   to UNKNOWN. Requirement or jurisdiction evidence does not count.
5. **Scoring.** Weight 0 → shown, not counted. PASS = 1, RISK = 0. UNKNOWN is counted as 0 under
   `assume_risk` / `assume_cost` and excluded under `unknown` / `ignore`. An UNKNOWN with
   **`verify=True`** (the data exists but only the landlord can settle it) is **always excluded**,
   whatever the policy.
6. **Hard block.** `blocking = hard_block and status == RISK and outcome.definitive_failure and not a data gap`.
   Missing data never disqualifies.

## Evaluators (`backend/app/services/evaluators.py`)

| Evaluator | Criterion (weight) | Logic | Fix cost items |
|---|---|---|---|
| `zoning_checker` | `zoning_use` (10, **hard block**) | (1) A disclosed `use_restrictions` tag that `use_restriction_blocks` maps to this use → RISK + **definitive failure**, in any city. (2) `zoning_mode: none` (Houston) → PASS with the city's `zoning_note` + a deed-restriction landlord question; the PASS needs the listing's restriction disclosure (`use_restrictions`, even `[]`) as observed evidence, so with `null` it is downgraded to UNKNOWN (not scored). (3) `zoning_mode: districts`: no zoning code → UNKNOWN; base district (suffixes like `-MU`, `-V` stripped) in the use table: permitted → PASS, conditional → RISK (CUP), prohibited → RISK + **definitive failure**, not listed / no table → UNKNOWN | none |
| `parking_checker` | `parking_sufficiency` (10) | Count = `visible_parking_count`, else Vexcel `estimated_parking_spaces`, else UNKNOWN (notes tiny parcel paving). Needed = per-property requirement (below). `count / needed >= min_ratio` (1.0) → PASS, else RISK. `vehicles_count` is context only. Cites the city rule | none |
| `ada_checker` | `ada_accessibility` (15) | Door `< min_width` (32 in.) or a stepped entrance → RISK | `door_widening`, `entrance_ramp` |
| `kitchen_checker` | `kitchen_equipment` (20, restaurant) | No kitchen needed → PASS; no equipment → RISK; equipment without a hood → RISK; hood unconfirmed → PASS + question | `kitchen_install` / `hood_exhaust`; fallback `kitchen_install` |
| `grease_checker` | `grease_interceptor` (10, restaurant) | Present → PASS, else RISK | `grease_interceptor`; fallback same |
| `operatory_checker` | `operatory_plumbing` (20, dental_clinic) | Plumbed rooms `>=` chairs → PASS, else RISK for the shortfall | `operatory_plumbing` × shortfall; fallback × capacity |
| `bathroom_checker` | `bathroom_count` (10) | Visible `>=` required → PASS, else RISK; cites the jurisdiction plumbing code | `restroom_add` × shortfall |
| `hvac_checker` | `hvac_capacity` (10) | Need = **max**(parsed need, `size_sqft / hvac_sqft_per_ton`). Capacity = `hvac_tons`, or its **suite share** when prorated (below). Enough → PASS. Short prorated share → **UNKNOWN, verify** (not scored, no cost, landlord question). Zero detected rooftop units, or direct (non-prorated) tonnage short → RISK + cost | `hvac_rtu` × ceil(shortfall / 5 tons); fallback sized from need |
| `electrical_checker` | `electrical_service` (5) | Service amps `>=` business amps → PASS, else RISK | `electrical_service_upgrade`; fallback same |
| `fire_safety_checker` | `fire_safety` (0, hard block) | IBC §903.2 trigger from `sprinkler_required_if` (restaurant: > 5,000 sq ft or >= 100 occupants). Not triggered → PASS; triggered and sprinklered → PASS; triggered and not sprinklered → RISK **priced as a retrofit, never definitive**; unconfirmed → UNKNOWN | `fire_sprinkler` × sq ft |
| `check_window_visibility` | `window_visibility` (5, restaurant) | `window_area >= min_area` (10 sq ft) → PASS, else RISK; no data → ignored (not scored) | none |
| `roof_checker` | `roof_condition` (5) | Vexcel `roof_condition >= min_condition` (3) and no serious defect (`tarp`, `structural-damage`; override with `thresholds.serious_defects`) → PASS (minor defects listed). Otherwise RISK, never definitive. No roof data → UNKNOWN, not scored | `roof_repair` × suite sq ft |

Because `fire_safety` and `roof_condition` are never definitive failures, **`zoning_use` is the only
criterion that disqualifies a space** in practice: through a prohibiting zoning district (Austin) or a
disclosed use restriction (any city, e.g. Houston's 4720 Washington Avenue).

### Parking requirement per property

`compliance_engine.build_inputs` sets `business_required_parking` for each property from
`requirements_parser.property_parking_requirement`:

- City with minimums (`parking_minimums: true` + a `parking_ratios` entry for the use, e.g. Houston):
  `ceil(ratio × size_sqft / 1000)` for the listing's actual size, **0 inside a `parking_exempt_areas`
  polygon** (Houston's Downtown and EaDo market-based areas), never below a number the user stated.
- City without minimums (Austin, default): the user's number, or the business guideline.

`code_required_parking` and `parking_requirement_note` are also exposed. When the user gives no number,
`Requirements.parking_source` is `"jurisdiction"` and the summary shows the city minimum for the
estimated space need (Houston restaurant, 1,400 sq ft → 14 spaces).

### HVAC proration (building-level Vexcel data)

Vexcel counts rooftop units for the **whole building**. With `thresholds.prorate_by_footprint: true`
and a known `building_footprint_sqft` larger than the listing, capacity is

```
hvac_tons_suite_share = hvac_tons × min(1, size_sqft / building_footprint_sqft)
```

emitted as evidence. Example, 1903 Yale St: 2 units ≈ 10 tons on a 19,863 sq ft building, 2,000 sq ft
suite → ≈ 1 ton vs 10 needed → UNKNOWN: "Building has 2 rooftop units (≈10 tons total); your prorated
share ≈1 ton vs 10 needed — ask the landlord which units serve your suite." Fixture tonnage without a
footprint (Austin) is taken as the suite's own and evaluated directly.

## Jurisdiction rules (`backend/config/jurisdictions.yaml`)

`config.jurisdiction_for(city, state)` looks up `"<city>-<state>"` (lowercase, spaces → `-`) and
merges it over `default`.

| Key | Used by | Houston, TX | Austin, TX | Default |
|---|---|---|---|---|
| `zoning_mode`, `zoning_note` | `zoning_checker` | `none` + note | `districts` | `districts` |
| `zoning`, `zoning_source` | `zoning_checker` | none; deed-restriction citation | Use table (LDC §25-2-491, simplified) | empty → UNKNOWN |
| `use_restriction_blocks`, `use_restriction_source` | `zoning_checker` | inherited tags; City-enforced deed restriction citation | inherited | `no_food_service`, `no_restaurant`, `no_cooking`, `office_only` → restaurant; `no_medical` → medical office |
| `parking_minimums`, `parking_ratios` | parser, `parking_checker` | true; restaurant 10.0, medical_office 3.5 per 1,000 sq ft | false | false |
| `parking_ratio_source`, `parking_ratio_cite` | `parking_checker` | §26-492 (Ord. 2013-208) / "Houston Code §26-492" | | |
| `parking_exempt_areas` | parser | Downtown, EaDo (§26-471) | none | none |
| `parking_note` | `parking_checker` | Ratios + market-based areas | Minimums eliminated Nov 2, 2023 | "No local parking rule loaded" |
| `plumbing_code` | `bathroom_checker` | 2021 UPC + Houston amendments, Table 422.1 | 2024 UPC as amended by Austin, Table 422.1 | IPC 2902.1 / UPC 422.1 |
| `name` | notes | "Houston, TX" | "Austin, TX" | "Generic (model codes)" |

`building_code`, `health_code`, `grease_code` and `plumbing_fixture_note` are recorded for reference
but not read by any evaluator. A city without an entry adds the assumption "No local rules loaded for
{city}, {state}; model codes used."

Austin zoning table: restaurant permitted in GR, CS, CS-1, CH, CBD, DMU; conditional in LR;
prohibited in LO, GO, NO, SF-1..3, MF-1..3. Medical office is permitted in LO, GO, GR, CS, CS-1, CH,
CBD, DMU; conditional in LR, NO.

## Outputs per property

- `criteria_results[]` and `compliance{id: {status, notes, source}}`
- Cost needs, which feed the [cost engine](COST_ENGINE.md)
- Landlord questions, de-duplicated
- `disqualifiers[]` (blocking criterion ids)
- Assumptions (e.g. "Grease interceptor ...: not confirmed, so the fix is budgeted (assume_cost).")

Demo results (restaurant, Houston, "40 seats, kitchen needed, 2 bathrooms"): 1903 Yale passes 10 of 11
criteria (HVAC is "verify"); 4720 Washington is RISK on `zoning_use` (`no_food_service`) and
disqualified; 801 St Emanuel passes parking with 0 on-site spaces (EaDo, no minimum); 240 W 19th is
RISK on roof condition (2/5). Austin: 456 Oak passes 10 of 11 (roof UNKNOWN: no Vexcel data offline, not scored);
789 Congress is disqualified (LO prohibits restaurant); 2100 E Cesar Chavez is RISK on zoning (LR-V →
conditional) but not disqualified.

Citations: [COMPLIANCE_RULE_SOURCES.md](COMPLIANCE_RULE_SOURCES.md).
