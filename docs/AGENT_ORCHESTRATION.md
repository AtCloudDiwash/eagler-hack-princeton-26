# Agent Orchestration

`POST /api/v1/analyze` runs a five-step pipeline in `backend/app/services/agent_orchestrator.py`.
Each "agent" is a plain, typed Python function, so it can be unit-tested on its own. Everything
is deterministic except the optional Claude parser in step 1, which falls back to regex.

```
analyze_properties(profile, properties)
├─ 1. parse_requirements(profile)                       once per request
└─ for each property → analyze_property(requirements, prop)
   ├─ get_business / jurisdiction_for / applicable_criteria
   ├─ 2. gather_observations(prop)                      vision agent
   ├─ 3. run_compliance(criteria, …)                    compliance / criteria agent
   ├─ 4. estimate(report.cost_needs, prop, business)    cost agent
   └─ 5. landlord_questions + draft_landlord_request    recommendation agent
└─ rank_results(results) → AnalyzeResponse
```

The router (`routers/analyze.py`) validates the business type (400), de-duplicates `property_ids`,
loads each property through `costar_provider.get_property` (404 if unknown), calls
`analyze_properties`, then stores the response with `db.save_run`.

## 1. Requirements parser agent (`requirements_parser.py`)

- **In:** `BusinessProfile`. **Out:** `(Requirements, parser_used)`.
- `regex_extract(details)` always runs. It reads capacity ("40 seats", "seating for 40"), bathrooms,
  parking ("20 parking spaces", "no parking"), square-footage ranges or bounds ("about 2000 sq ft"
  becomes ±20%), max rent ("$5k/month", "budget 5000"), and kitchen need ("kitchen needed",
  "no kitchen"). Number words ("forty") are normalized first.
- If `ANTHROPIC_API_KEY` is set and details are non-empty, `claude_extract` asks Claude
  (`ANTHROPIC_MODEL`, default `claude-haiku-5-5`, 8 s timeout, no retries) for schema-constrained
  JSON. Values are range-checked and merged **over** the regex fields. Any exception, refusal or
  non-`end_turn` stop falls back to regex and logs a warning.
- `build_requirements` fills unstated fields from `business_types.yaml` and records each default in
  `assumptions`. It computes occupant load, guideline parking, restrooms, HVAC tons and electrical amps.

## 2. Vision agent (`gather_observations`)

- **In:** `Property`. **Out:** `(observations: dict[str, Evidence], Media)`.
- CoStar listing facts: `zoning_code` (confidence 0.95), `previous_use`, `size_sqft`.
- `matterport_provider.get_interior(prop)`: interior facts (`door_width_inches`,
  `step_free_entrance`, `kitchen_equipment_visible`, `hood_present`, `grease_interceptor_present`,
  `bathrooms_visible`, `plumbed_operatories`, `electrical_service_amps`, `sprinklered`,
  `window_area`) plus the floor-plan and 3D-tour URLs.
- `vexcel_provider.get_aerial(prop)`: aerial facts (`visible_parking_count`, `hvac_tons`) plus the
  aerial URL.
- Facts come from `fixtures/observations.json` in every mode (no live image detection). A fact that is
  absent is unknown, which drives the missing-data policies.

## 3. Compliance / criteria agent (`compliance_engine.run_compliance`)

- **In:** applicable criteria (`criteria_manager.applicable_criteria(business_type, city, state)`),
  requirements, property, observations, jurisdiction rules, business profile.
- `build_inputs` flattens observations plus requirement and listing values (`business_required_parking`,
  `business_required_bathrooms`, `business_capacity`, `required_hvac_tons`,
  `required_electrical_amps`, `occupant_load`, `needs_kitchen`, `size_sqft`, `monthly_rent`) into the
  names that `required_inputs` can reference.
- `evaluate_criterion` applies the registry semantics (missing inputs → UNKNOWN, missing-data
  policy, `evidence_required` downgrade, hard block only on a definitive failure) and calls the
  evaluator from `evaluators.py`.
- **Out:** `ComplianceReport` with `criteria_results`, `cost_needs` (fix items), landlord
  `questions`, `assumptions`, `disqualifiers`, and `score` (`scoring.weighted_score`).

Details: [COMPLIANCE_AGENT.md](COMPLIANCE_AGENT.md), [CRITERIA_REGISTRY.md](CRITERIA_REGISTRY.md).

## 4. Cost agent (`cost_engine.estimate`)

- **In:** the report's cost needs, the property, the business profile.
- Merges duplicate needs, prices them from `costs.yaml`, adds general conditions, contingency and
  permits, subtracts the TI allowance, adds build-out months, and computes cost to open and
  first-year cost. Every value is a min/max range. Details: [COST_ENGINE.md](COST_ENGINE.md).

## 5. Recommendation agent

- `landlord_questions(report, costs, prop)`: the evaluators' questions, plus a TI-increase question
  when there is construction work and plus a free-rent-during-build-out question. Duplicates are removed.
- `draft_landlord_request(requirements, prop, report, costs)`: a deterministic plain-text letter
  that lists the needed improvements with ranges, the fit-out total, requests (TI allowance and rent
  abatement), and up to 6 open questions.
- `analyze_property` also appends assumptions: a missing local jurisdiction ("model codes used")
  and low-confidence observations (confidence < 0.7, "verify on site").

## Ranking (`rank_results`)

`rank_results(results, min_score)` sets `weak_fit = not disqualified and score < min_score`, then sorts by
`(tier, first_year_cost.min, first_year_cost.max, -score)` where tier is 0 qualifying, 1 weak fit, 2 disqualified.
`min_score` comes from `ranking_settings()` (`costs.yaml` `ranking.min_score`; missing or 0 turns the gate off).

1. **Qualifying** spaces (not disqualified, `score >= ranking.min_score`, default 25) by
   first-year cost, cheapest first.
2. **Weak fit** spaces (`score < min_score`): `weak_fit: true`, ranked after every qualifying space
   even when they are cheaper.
3. **Disqualified** spaces (a hard-block criterion failed definitively) are always last.

Ties are broken by higher score. `AnalyzeResponse.ranking_basis` states the rule in plain English,
and `AnalyzeResponse.min_score` echoes the threshold.

Demo outcome (restaurant, "40 seats, kitchen needed, 2 bathrooms, 20 parking spaces", Austin TX,
all 4 properties): #1 property-456 (score 100), #2 property-123 (31.6), #3 property-321 (0.0, weak
fit), #4 property-789 (disqualified: `zoning_use`).

## Response assembly

`analyze_properties` adds `analysis_id` (uuid4 hex), `created_at`, `ranking_basis`, `mode`
(provider modes plus the parser actually used) and the `costs.yaml` disclaimer. Properties are analyzed
sequentially; with mock data a 4-property run takes milliseconds.
