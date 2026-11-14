# Agent Orchestration

`POST /api/v1/analyze` runs a five-step pipeline in `backend/app/services/agent_orchestrator.py`,
then an optional sixth "explanation" step. Each "agent" is a plain, typed Python function, so it can be
unit-tested on its own. The LLM (`backend/app/services/llm.py`, local Ollama `qwen3:8b` by default) is
used in exactly two places: extracting fields in step 1 (regex fallback) and writing the grounded
`ai_summary` in step 6 (`null` fallback). Compliance statuses, costs, scores and ranks are always
computed by the deterministic rules.

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
└─ 6. summarize_ranking(response) → ai_summary          explanation agent, once per request (optional)
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
- If details are non-empty and `llm.is_available()` (Ollama answers `GET /api/tags` and the model is
  pulled, cached 30 s; or `LLM_PROVIDER=anthropic` with a key), `llm_extract` asks the LLM for the same
  seven raw fields as schema-constrained JSON (`LLM_SCHEMA`, nullable ints / number / bool, "null for
  anything not mentioned, do not guess defaults"). Ollama is called at `POST /api/chat` with the JSON
  schema as `format`, `think: false`, `temperature: 0`, `keep_alive` and a fixed `num_ctx`. Values are
  range-checked (`_validate_llm_fields`) and merged **over** the regex fields. Any exception (Ollama down,
  timeout, truncated output, invalid JSON, Claude refusal) falls back to regex and logs a warning.
  `parser_used` is `"ollama"`, `"claude"` or `"regex"`. Warm qwen3:8b on an M4 Pro: 1.4-1.7 s.
- `build_requirements` fills unstated fields from `business_types.yaml` and records each default in
  `assumptions`. It computes occupant load, parking, restrooms, HVAC tons and electrical amps. Parking:
  the user's number; else the **city code minimum** for the estimated space need when
  `jurisdictions.yaml` sets one (`parking_source: "jurisdiction"`, e.g. Houston §26-492: 10 per 1,000
  sq ft × 1,400 sq ft = 14); else the business guideline. When the user states a number in a city with
  minimums, an assumption says each property is checked against the larger of the two.

## 2. Vision agent (`gather_observations`)

- **In:** `Property`. **Out:** `(observations: dict[str, Evidence], Media)`.
- CoStar listing facts: `zoning_code` (confidence 0.95, when the listing has one), `previous_use`,
  `size_sqft`. (`use_restrictions` is read from the `Property` by the zoning check.)
- `matterport_provider.get_interior(prop)`: interior facts (`door_width_inches`,
  `step_free_entrance`, `kitchen_equipment_visible`, `hood_present`, `grease_interceptor_present`,
  `bathrooms_visible`, `plumbed_operatories`, `electrical_service_amps`, `sprinklered`,
  `window_area`) plus the floor-plan and 3D-tour URLs. Always fixtures today.
- `vexcel_provider.get_aerial(prop)`: aerial and oblique URLs, `aerial_source`, attribution, fixture
  aerial facts and, in live mode, **live facts** from `/property/extract` (rooftop AC units, HVAC tons,
  paved area, parking estimate, vehicles, roof condition/material/defects, footprint + box, building
  type). Live facts win over fixture facts of the same key; fixture facts fill the gaps. Live calls are
  cached on disk and fall back per item ([INTEGRATIONS.md](INTEGRATIONS.md#vexcel-aerial-imagery--property-intelligence-vexcel_providerpy)).
- Box rule: live / snapshot boxes are positioned on the live ortho, so they are dropped when the
  aerial is the placeholder ([VISION_OVERLAYS.md](VISION_OVERLAYS.md)).
- A fact that is absent is unknown, which drives the missing-data policies.

## 3. Compliance / criteria agent (`compliance_engine.run_compliance`)

- **In:** applicable criteria (`criteria_manager.applicable_criteria(business_type, city, state)`),
  requirements, property, observations, jurisdiction rules, business profile.
- `build_inputs` flattens observations plus requirement and listing values (`business_required_parking`,
  `business_required_bathrooms`, `business_capacity`, `required_hvac_tons`,
  `required_electrical_amps`, `occupant_load`, `needs_kitchen`, `size_sqft`, `monthly_rent`,
  `use_restrictions`) into the names that `required_inputs` can reference. `business_required_parking`
  is recomputed **per property** (city minimum for its size and location, 0 in a market-based parking
  area, never below the user's number), with `code_required_parking` and `parking_requirement_note`.
- `evaluate_criterion` applies the registry semantics (missing inputs → UNKNOWN, missing-data
  policy, `evidence_required` downgrade, "verify" UNKNOWNs excluded from the score, hard block only on a
  definitive failure) and calls the evaluator from `evaluators.py`.
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

1. **Qualifying** spaces (not disqualified, `score >= ranking.min_score`, currently 55) by
   first-year cost, cheapest first.
2. **Weak fit** spaces (`score < min_score`): `weak_fit: true`, ranked after every qualifying space
   even when they are cheaper (by first-year cost among themselves).
3. **Disqualified** spaces (a hard-block criterion failed definitively) are always last.

Ties are broken by higher score. `AnalyzeResponse.ranking_basis` states the rule in plain English,
and `AnalyzeResponse.min_score` echoes the threshold.

Demo outcome (restaurant, "40 seats, kitchen needed, 2 bathrooms", Houston TX, all 5 properties; same
in mock and live mode): #1 property-hou-01 1903 Yale (score 100, first-year $93.2k-$104.5k),
#2 property-hou-04 801 St Emanuel (66.7, $114.0k-$174.8k), #3 property-hou-05 3701 Kirby (50.0, weak
fit), #4 property-hou-02 240 W 19th (16.7, weak fit), #5 property-hou-03 4720 Washington
(disqualified: `zoning_use`, `no_food_service` restriction). With "20 parking spaces" added, hou-04
scores 55.6 and the order is unchanged.

Austin offline dataset ("40 seats, kitchen needed, 2 bathrooms, 20 parking spaces"): #1 property-456
(100), #2 property-321 (0.0, weak fit), #3 property-123 (31.6, weak fit), #4 property-789
(disqualified: LO zoning).

## 6. Explanation agent (`ranking_summary.summarize_ranking`)

Runs once, **after** ranking, so it can only explain a finished result.

- **In:** the assembled `AnalyzeResponse`. **Out:** `AISummary | None` (`text`, `per_property`
  `{property_id: sentence}`, `model`, `grounded: true`).
- `build_digest` turns the response into a compact JSON digest: business, requirements, ranking basis,
  `min_fit_score`, and per property (rank order) the status (qualifies / weak fit / disqualified), fit
  score, rent, first-year cost and cost to open as preformatted `$` strings, the top 3 cost items, up to 3
  RISK/UNKNOWN flags, the disqualifying criteria and `rent_vs_budget`.
- One `llm.chat_json` call with a schema whose `per_property[].property_id` is an enum of this run's
  ids. The system prompt says: explain only from the digest, never change the ranking or contradict a
  status, quote dollar amounts exactly, mention every disqualified / weak-fit property, use addresses.
- **Guardrail** (`validate_summary` / `check_grounded`): every `$` figure must match a digest number
  (within the rounding written, at least $500), every quoted fit score must match a digest score (within
  0.5), every `per_property` key must be a known id; length limits apply. Any failure, and any LLM error,
  gives `ai_summary: null`. The analysis itself never fails because of the summary.
- The guardrail checks numbers and ids only. A wrong *non-numeric* claim (e.g. calling a PASS a risk)
  could still get through; the UI labels the panel as AI-written with the caveat "costs and compliance
  are rule-based".
- Warm qwen3:8b on an M4 Pro: 5.6-6.1 s (the bulk of the AI time).

## Response assembly

`analyze_properties` adds `analysis_id` (uuid4 hex), `created_at`, `ranking_basis`, `mode`
(provider modes, the parser actually used, and `llm`: the model label used for the parse or the
summary in this run, else `"none"`), the `costs.yaml` disclaimer and `ai_summary`. It logs per-phase
timings (`parse`, `evaluate+rank`, `summary`, `total`). Properties are analyzed sequentially; with mock
data or a warm Vexcel cache the deterministic part of a 5-property run takes milliseconds. With the local
LLM a whole analysis takes about 7 s warm (about 14 s if the model is cold; qwen3:14b about 13 s warm).
A cold live run makes three parallel Vexcel calls per property (bounded by `PROVIDER_TIMEOUT_SECONDS`).
