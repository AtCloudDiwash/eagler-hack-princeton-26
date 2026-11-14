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
```

## Latest results (2026-11-14)

| Suite | Result |
|---|---|
| Backend `venv/bin/pytest -q` | **88 passed** |
| Frontend `npm test` | **28 passed** (5 files) |
| Frontend `npm run lint` | clean (no warnings or errors) |
| Playwright `npm run e2e` | **4 passed** (2 tests × desktop and mobile 375px projects, ~7 s) |

## Backend (`backend/tests/`, pytest)

`conftest.py` pins env vars **before** importing the app: a temp `DATABASE_URL`, `USE_MOCK_DATA=true`,
and every API key plus `CRITERIA_PATH` blanked. Tests therefore never hit the network or your real
SQLite file. It also provides helpers (`profile`, `make_property`, `obs`, `make_criterion`,
`make_ctx`) and a session `TestClient`.

| File | Tests | Covers |
|---|---|---|
| `test_api.py` | 13 | Every endpoint via `TestClient`: health modes, business types, criteria filtering, property filters, analyze errors (400/404/422), full response shape, demo ranking (456, 123, 321 weak fit, 789 disqualified last on zoning), SQLite round-trip (`GET /analyses/{id}` equals the POST body), history order + `limit`, runs stored before the min-score gate still load with defaults, static media served, CORS, malformed registry → clear 500 |
| `test_compliance_engine.py` | 12 | Missing input → UNKNOWN; `assume_risk` / `assume_cost` (fallback cost) / `unknown` / `ignore`; `evidence_required` downgrade (requirement evidence doesn't count); hard block only on a definitive failure; unknown or crashing evaluator → UNKNOWN; weight 0 not scored; report aggregation; `check_parking` / `check_ada` helpers |
| `test_cost_engine.py` | 7 | Each vs per-sq-ft pricing, unknown item, `merge_needs`, permits-only case, soft costs + TI + build-out months, TI never makes net negative, `estimate_cost` helper |
| `test_criteria_manager.py` | 9 | Real registry loads; business / jurisdiction filters; invalid entry, missing field, duplicate id and wrong shape errors name the entry; score normalization; **adding a criterion via config changes results** (scale-criteria); **weight change takes effect without a code change**; min-score gate is config-driven |
| `test_evaluators.py` | 20 | Every YAML evaluator is registered; base zoning district parsing; Austin zoning permitted / conditional / prohibited; unlisted district and no table; parking, ADA, kitchen, grease, operatories, bathrooms, HVAC (larger of need and space), electrical, fire safety, window visibility |
| `test_providers.py` | 5 | Mock is the default; mock interior/aerial; vision agent merges sources and boxes; live failures fall back to fixtures; live CoStar mapping |
| `test_requirements_parser.py` | 22 | Regex extraction table; sq ft not mistaken for rent; demo profile; defaults recorded as assumptions; dental defaults; unknown type; Claude merge over regex, invalid values dropped, failure (timeout / error / bad JSON) and refusal fall back to regex, no key → Claude never called (fake client, no network) |

Ranking with the min-score gate (qualifying → weak fit → disqualified) is asserted by the demo ranking
test in `test_api.py` and `test_min_score_gate_is_config_driven`.

## Frontend unit (`frontend/test/`, Vitest + React Testing Library, jsdom)

Config: `vitest.config.mts` (`@vitejs/plugin-react`, tsconfig paths, `test/setup.ts` loads
`@testing-library/jest-dom/vitest` and cleans up after each test). The fixture
`test/fixtures/analysis.json` is a real `POST /analyze` response.

| File | Tests | Covers |
|---|---|---|
| `AnalysisCard.test.tsx` | 9 | Headline numbers, every criterion with a status badge and line-item reasons, overlay boxes for Vexcel and Matterport, landlord questions + letter, disqualified flag with the blocking criterion, Weak fit badge only for `weak_fit` results (older runs without the field are not weak), `ComparisonTable` columns in rank order and weak-fit badges |
| `CriteriaTable.test.tsx` | 5 | Registry-driven: renders 1 / 7 / 23 criteria (any count), shows all fields, empty registry |
| `StatusBadge.test.tsx` | 4 | PASS / RISK / UNKNOWN colors, unexpected status → UNKNOWN |
| `format.test.ts` | 5 | Currency, ranges, months, rent, N/A fallbacks, value/key formatting |
| `overlay.test.ts` | 5 | `boxToStyle` math, clamping and rounding; `overlayEvidence` filtering and de-duplication |

## End-to-end (`frontend/e2e/`, Playwright)

`playwright.config.ts` starts the backend (`../backend/venv/bin/uvicorn`, mock mode, throwaway SQLite
in the OS temp dir) and `npm run dev`, or reuses servers already running locally. It runs Chromium in
two projects: **desktop** (1280×800) and **mobile** (375×812, touch).

| Spec | Covers |
|---|---|
| `demo-flow.spec.ts` › demo flow | Home form → `/properties` shows the 4 Austin listings → Select all → Compare 4 → `/analysis/{id}` with 4 ranked cards → reload re-reads the report from SQLite. On mobile, asserts no horizontal overflow on every page |
| `demo-flow.spec.ts` › error state | Listings call forced to 500 → "Couldn't load spaces" alert with the API detail → Try again recovers |

## Manual checks (before the demo)

1. `curl localhost:8000/health` → `{"status":"ok","mode":{... "mock" ..., "parser":"regex"}}`.
2. Header pill shows "API · mock data". Stop the backend → "API offline", the form still renders
   (fallback business types), and `/properties` shows an error with retry.
3. Run the demo flow in [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) and confirm the ranking 456, 123, 321
   (weak fit), 789 (disqualified).
4. Overlays: the property-123 aerial shows parking + HVAC boxes; its floor plan shows door and
   restroom boxes. No 3D tour → "No Matterport 3D tour" note.
5. Copy the landlord letter; reload the report URL; open it from "Recent analyses".
6. Config scaling: change a weight or threshold in `backend/criteria.yaml`, run a new comparison and
   see the score change. Break the YAML → the UI shows the API's "Criteria registry error" detail.
   Revert.
7. Unknown ids: `/analysis/doesnotexist` → "Analysis not found"; `/properties?type=restaurant&city=Nowhere`
   → "No spaces found".
8. Responsive: 375px width, no horizontal page scroll; the comparison table scrolls inside its box.

## Gaps / not covered

No component test for `BusinessProfileForm` or `PropertyCard` interaction (covered by E2E instead),
no live-provider contract tests (endpoints are placeholders), and no CI pipeline (run locally).
