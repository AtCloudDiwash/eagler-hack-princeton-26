# Test Plan

Three automated layers: backend pytest (unit + API integration), frontend Vitest (components and
helpers), and Playwright E2E (the live demo flow in a real browser). After them come the manual demo
checks.

## Commands

```bash
cd backend && venv/bin/pytest -q      # backend unit + integration
cd frontend && npm test               # Vitest (vitest run)
cd frontend && npm run lint           # ESLint
cd frontend && npm run e2e            # Playwright (first time: npx playwright install chromium)
cd backend && venv/bin/python scripts/llm_live_check.py   # manual: demo against a running Ollama (not pytest)
```

## Latest results (2026-11-14)

| Suite | Result |
|---|---|
| Backend `venv/bin/pytest -q` | **178 passed** (10 modules, ~0.5 s) |
| Frontend `npm test` | **64 passed** (8 files) |
| Frontend `npm run lint` | clean (no warnings or errors) as of the last lint run |
| Playwright `npm run e2e` | **6 passed** (3 tests × desktop and mobile 375px projects, ~11 s); last run before the LLM work, not re-run in this pass |

## Backend (`backend/tests/`, pytest)

`conftest.py` pins env vars **before** importing the app: a temp `DATABASE_URL`, `USE_MOCK_DATA=true`,
`LLM_PROVIDER=none` (tests that need an LLM install a fake one), and every API key plus `CRITERIA_PATH` blanked, and an autouse fixture points the Vexcel cache at a temp
dir. Tests therefore never hit the network, a running Ollama, your real SQLite file or your Vexcel cache; Vexcel tests use
a fake HTTP layer and a recorded `/property/extract` response (`tests/fixtures/vexcel_property_extract.json`,
a Los Angeles building). It also provides helpers (`profile`, `make_property`, `obs`, `make_criterion`,
`make_ctx`) and a session `TestClient`.

| File | Tests | Covers |
|---|---|---|
| `test_api.py` | 13 | Every endpoint via `TestClient`: health modes (incl. `llm: "none"`, and `claude` / `anthropic:<model>` only with `LLM_PROVIDER=anthropic` + key), full response shape incl. `ai_summary: null`, business types, criteria filtering, property filters, analyze errors (400/404/422), full response shape, Austin ranking (456 first, 321 and 123 weak fits, 789 disqualified last on zoning), SQLite round-trip (`GET /analyses/{id}` equals the POST body), history order + `limit`, runs stored before the min-score gate still load with defaults, static media served, CORS, malformed registry → clear 500 |
| `test_compliance_engine.py` | 12 | Missing input → UNKNOWN; `assume_risk` / `assume_cost` (fallback cost) / `unknown` / `ignore`; `evidence_required` downgrade (requirement evidence doesn't count); hard block only on a definitive failure; unknown or crashing evaluator → UNKNOWN; weight 0 not scored; report aggregation; `check_parking` / `check_ada` helpers |
| `test_cost_engine.py` | 7 | Each vs per-sq-ft pricing, unknown item, `merge_needs`, permits-only case, soft costs + TI + build-out months, TI never makes net negative, `estimate_cost` helper |
| `test_criteria_manager.py` | 9 | Real registry loads; business / jurisdiction filters; invalid entry, missing field, duplicate id and wrong shape errors name the entry; score normalization; **adding a criterion via config changes results** (scale-criteria); **weight change takes effect without a code change**; min-score gate is config-driven |
| `test_evaluators.py` | 20 | Every YAML evaluator is registered; base zoning district parsing; Austin zoning permitted / conditional / prohibited; unlisted district and no table; parking, ADA, kitchen, grease, operatories, bathrooms, HVAC (larger of need and space), electrical, fire safety, window visibility |
| `test_houston.py` | 30 | Houston jurisdiction lookup; no-zoning PASS with deed-restriction note, but UNKNOWN when the listing says nothing about restrictions (`evidence_required`); use restriction disqualifies in Houston and even where zoning permits; restriction on another use doesn't block; parking from the §26-492 ratio with citation, EaDo market-based area has no minimum, city minimum raises the user's number, Austin keeps the guideline; Houston listings; full Houston restaurant analysis and top pick (with and without "20 parking spaces"); HVAC proration, short share → verify UNKNOWN excluded from the score, share meeting need passes, zero units / direct shortfall → RISK + cost, proration toggle, Austin HVAC unchanged; `listing_source` / `use_restrictions` on results |
| `test_vexcel.py` | 36 | Normalizing a recorded `/property/extract` (nested and flat shapes, thresholds, partial data); footprint box math, clipping, box matches the visible roof; cache miss then hit; request shape and **key only in the `X-API-KEY` header**; sanitized cache dir; 404 keeps imagery + fixture facts; 403 geofence → placeholders; timeouts are transient; non-image rejected; **key never logged**; mock mode makes no calls; live facts override fixtures; old stored runs validate; `roof_checker` (incl. missing data policy, repair priced); parking falls back to the paved-area estimate, estimate omitted below one space, vehicles as context only; HVAC uses live tons; snapshot script merge / stale-fact removal / `--from-cache` without key or network; snapshot and live boxes dropped over placeholder imagery |
| `test_llm.py` | 24 | Fake Ollama (`httpx.get` / `httpx.post` replaced, no network): parser uses the Ollama result (request has `format` schema, `think: false`, temperature 0); falls back to regex on timeout, connection refused, invalid JSON, non-object JSON, truncated (`done_reason: "length"`) and HTTP 500; Ollama down or model not pulled → no chat call; availability cached and a timeout marks Ollama unavailable; `<think>` blocks stripped; digest is compact and complete; guardrail accepts digest numbers and rejects invented dollar figures (incl. "$9.9 million"), invented scores and unknown property ids; summary attached to an analysis; ungrounded summary → `null` with the ranking unchanged; `LLM_PROVIDER=none` → no calls; old stored runs default to `ai_summary: null`; `/analyze` succeeds with Ollama down; `ai_summary` stored and re-read; `/health` reports the LLM |
| `test_providers.py` | 5 | Mock is the default; mock interior/aerial; vision agent merges sources and boxes; live failures fall back to fixtures; live CoStar mapping |
| `test_requirements_parser.py` | 22 | Regex extraction table; sq ft not mistaken for rent; demo profile; defaults recorded as assumptions; dental defaults; unknown type; Claude provider (`LLM_PROVIDER=anthropic`, fake client, no network): merge over regex, invalid values dropped, failure (timeout / error / bad JSON) and refusal fall back to regex, no key → Claude never called |

Ranking with the min-score gate (qualifying → weak fit → disqualified) is asserted by the demo ranking
test in `test_api.py` and `test_min_score_gate_is_config_driven`.

## Frontend unit (`frontend/test/`, Vitest + React Testing Library, jsdom)

Config: `vitest.config.mts` (`@vitejs/plugin-react`, tsconfig paths, `test/setup.ts` loads
`@testing-library/jest-dom/vitest` and cleans up after each test). The fixture
`test/fixtures/analysis.json` is a real `POST /analyze` response.

| File | Tests | Covers |
|---|---|---|
| `AiSummary.test.tsx` | 15 | `llmLabel` / `parserLabel` ("Local AI · qwen3:8b", "Claude · ...", unknown, missing); `AiSummaryPanel` renders text, model badge and caveat, and nothing when the summary is null / missing / blank; per-property "why" sentence in the `AnalysisCard` header (omitted when absent); "Why (AI)" comparison-table row only when the summary covers a property; parser + LLM mode badges, none for older runs; `AnalysisView` puts the panel above the table, renders older runs without `ai_summary` / `mode.llm`, hides the panel for `null`; header pill "Local AI ready" only for an `ollama:` model (parser / llm ignored for mock / live); "Writing summary (local AI)" progress step only when an LLM is configured |
| `AnalysisCard.test.tsx` | 9 | Headline numbers, every criterion with a status badge and line-item reasons, overlay boxes for Vexcel and Matterport, landlord questions + letter, disqualified flag with the blocking criterion, Weak fit badge only for `weak_fit` results (older runs without the field are not weak), `ComparisonTable` columns in rank order and weak-fit badges |
| `CriteriaTable.test.tsx` | 5 | Registry-driven: renders 1 / 7 / 23 criteria (any count), shows all fields, empty registry |
| `StatusBadge.test.tsx` | 4 | PASS / RISK / UNKNOWN colors, unexpected status → UNKNOWN |
| `format.test.ts` | 5 | Currency, ranges, months, rent, N/A fallbacks, value/key formatting |
| `overlay.test.ts` | 5 | `boxToStyle` math, clamping and rounding; `overlayEvidence` filtering and de-duplication |
| `MediaPanel.test.tsx` | 12 | "Live · Vexcel" badge + attribution for live imagery (with a fallback attribution), "Placeholder imagery" otherwise; Top-down / Angled tabs only when `oblique_url` is set, overlays stay on the top-down view; building footprint box with its label; square aerial frame; live dots on live evidence only; older stored runs without the new fields; parking source labels ("city code") |
| `PropertyCard.test.tsx` | 9 | "Sample listing" badge + tooltip only for `listing_source: "sample"` (not costar / null / absent); use-restriction warning line (one, several, empty, null, absent) |

## End-to-end (`frontend/e2e/`, Playwright)

`playwright.config.ts` starts the backend (`../backend/venv/bin/uvicorn`, mock mode, throwaway SQLite
in the OS temp dir) and `npm run dev`, or **reuses servers already running locally** (then it runs
against your running backend, its mode and its database). It runs Chromium in
two projects: **desktop** (1280×800) and **mobile** (375×812, touch).

| Spec | Covers |
|---|---|
| `demo-flow.spec.ts` › demo flow | Austin: home form → `/properties` shows the 4 Austin listings → Select all → Compare 4 → `/analysis/{id}` with 4 ranked cards → reload re-reads the report from SQLite. On mobile, asserts no horizontal overflow on every page |
| `houston-flow.spec.ts` › Houston demo flow | Houston: 5 sample listings with the "Sample listing" badge and 4720 Washington's "Use restriction: no food service" line → select 4 cards → Compare 4 → 1903 Yale is Rank #1, 4720 Washington is Disqualified, the zoning result mentions "no zoning". No overflow on mobile |
| `demo-flow.spec.ts` › error state | Listings call forced to 500 → "Couldn't load spaces" alert with the API detail → Try again recovers |

## Manual checks (before the demo)

1. `curl localhost:8000/health` → `{"status":"ok","mode":{... "mock" ..., "parser":"ollama","llm":"ollama:qwen3:8b"}}`
   with Ollama running and `qwen3:8b` pulled; `"parser":"regex","llm":"none"` without it.
2. Header pill shows "API · mock data" (plus "· Local AI ready" on wide screens when Ollama is up). Stop the backend → "API offline", the form still renders
   (fallback business types), and `/properties` shows an error with retry.
3. Run the Houston demo flow in [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) and confirm the ranking 1903 Yale,
   801 St Emanuel, 3701 Kirby (weak fit), 240 W 19th (weak fit), 4720 Washington (disqualified). Austin
   (mock): 456, 321 (weak fit), 123 (weak fit), 789 (disqualified).
4. Overlays (mock): the Houston floor plans show door / kitchen / restroom boxes; the placeholder aerial
   shows the hand-made parking box and **no** footprint box. No 3D tour → "No Matterport 3D tour" note.
5. Live Vexcel (`USE_MOCK_DATA=false` + key, warm cache): `/health` shows `vexcel: "live"`; each Houston
   card shows "Live · Vexcel", the attribution, a dashed "Building footprint" box, an Angled tab with a
   real oblique (not a second top-down image), and live dots; `/static/vexcel-cache/...` returns 200;
   the ranking matches mock mode; the key does not appear in the server log or the browser network tab.
6. Copy the landlord letter; reload the report URL; open it from "Recent analyses".
6a. Local LLM (Ollama up, model warm): `venv/bin/python scripts/llm_live_check.py` prints the parsed
   requirements, an `ai_summary` and per-call timings (warm qwen3:8b on an M4 Pro: parse 1.4-1.7 s,
   summary 5.6-6.1 s). In the UI the progress overlay shows "Writing summary (local AI)", the report
   shows the AI summary panel with the "Local AI · qwen3:8b" badge and caveat, a "Why (AI)" row and one
   sentence per card; for the demo text the parsed requirements, ranking and numbers match a run with `LLM_PROVIDER=none` (if not, the LLM read a field differently: compare the requirement chips). Read the
   summary for wrong non-numeric claims (the guardrail only checks numbers and ids). Stop Ollama → within
   30 s the parser badge reads Regex, no summary panel, same ranking.
7. Config scaling: change a weight or threshold in `backend/criteria.yaml`, run a new comparison and
   see the score change. Break the YAML → the UI shows the API's "Criteria registry error" detail.
   Revert.
8. Unknown ids: `/analysis/doesnotexist` → "Analysis not found"; `/properties?type=restaurant&city=Nowhere`
   → "No spaces found".
9. Responsive: 375px width, no horizontal page scroll; the comparison table scrolls inside its box.

## Gaps / not covered

No component test for `BusinessProfileForm` (covered by E2E instead); no automated test against a real
Ollama model (the fake server covers the protocol; `llm_live_check.py` and manual check 6a cover the model),
and no automated check of the *wording* of a summary beyond numbers and ids; no E2E assertion of the AI
summary panel (E2E runs in whatever LLM mode the backend has); no automated test against the
real Vexcel API (the recorded response and the manual live check above cover it); no CoStar / Matterport
contract tests (endpoints are placeholders); no E2E assertion of live imagery; no CI pipeline (run locally).
