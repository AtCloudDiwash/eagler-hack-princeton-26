# Turnkey Matchmaker

**HackPrinceton Fall 2026.** Turnkey Matchmaker helps small business owners pick a commercial space by
comparing the **total cost to open** (fit-out + rent during build-out + first-year rent) instead of
the asking rent alone. It combines listing data (CoStar), interior scans (Matterport) and **live
Vexcel aerial imagery and AI property facts**, runs a config-driven compliance/criteria agent (zoning
and deed restrictions, the city's parking code, ADA, kitchen, grease interceptor, restrooms, HVAC,
electrical, sprinklers, storefront visibility, roof condition) and returns a ranked comparison with
cost ranges, citations, evidence overlays and a drafted landlord letter.

The demo city is **Houston, TX** (the sponsor's Vexcel key is geofenced to Los Angeles and Houston);
the original Austin, TX listings remain as an offline dataset. Everything runs offline in **mock mode**
by default with no API keys; mock mode replays snapshots of the real Vexcel facts, so it ranks exactly
like live mode.

## Features (as built)

- **Business profile form**: business type (from `backend/config/business_types.yaml`), plain-English
  requirements ("40 seats, kitchen needed, 2 bathrooms, 20 parking spaces"), city/ZIP and state.
- **Requirements parser agent**: deterministic regex parser; optional Claude parser when
  `ANTHROPIC_API_KEY` is set (falls back to regex on any error). Unstated needs are filled from the
  business profile and listed as assumptions.
- **Candidate spaces**: 5 Houston **sample listings** at real buildings (rent/size illustrative,
  "Sample listing" badge, disclosed use restrictions) plus 4 Austin listings, in CoStar's shape.
- **Live Vexcel integration** (`USE_MOCK_DATA=false` + `VEXCEL_API_KEY`): top-down and angled (oblique)
  imagery plus `/property/extract` AI facts (rooftop AC units, roof condition/material/defects, building
  footprint, paved area, vehicles). Cached server-side; the key never reaches the browser.
- **Compliance / criteria agent**: every criterion in `backend/criteria.yaml` returns
  PASS / RISK / UNKNOWN with notes, a source citation and evidence. Houston rules are config-driven: no
  zoning (deed restrictions instead), §26-492 parking ratios, no minimum in market-based areas. A
  disclosed use restriction or a prohibiting zoning district disqualifies a space. Building-level HVAC is
  prorated to the suite; a short share is "verify with landlord" (not scored, not priced).
- **Deterministic cost engine**: cost bands from `backend/config/costs.yaml`, ranges only (no ML),
  with general conditions, contingency, permits, TI allowance and build-out months.
- **Ranking**: spaces that clear the minimum fit score (`ranking.min_score`, 55) rank by
  first-year cost, then "weak fit" spaces, then disqualified ones. Ties are broken by score.
- **Analysis report**: side-by-side table, per-property cost breakdown, criteria grouped by domain,
  Vexcel aerial ("Live · Vexcel" badge, Top-down / Angled tabs, building footprint box) and floor-plan
  overlays, observations with confidence and live markers, assumptions, landlord questions, and a
  copyable landlord request letter.
- **Run history**: every analysis is stored in SQLite and has a shareable URL `/analysis/{id}`;
  recent runs are listed on the home page.
- **Config-only scaling**: add or re-weight criteria in `criteria.yaml`. The backend reloads it on
  the next request and the UI renders any number of criteria.

## Tech stack

| Layer | Stack |
|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4 (`@theme` tokens in `app/globals.css`), Heroicons, hand-rolled UI components |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLModel/SQLite, PyYAML, httpx, optional `anthropic` SDK |
| Tests | pytest (backend), Vitest + React Testing Library (frontend), Playwright E2E (`npm run e2e`) |

## Quickstart

Prerequisites: Python 3.10+ (built with 3.12) and Node 20+ (built with 24).

**Backend** (http://localhost:8000, interactive docs at `/docs`):

```bash
cd backend
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp ../.env.example .env          # optional; placeholders mean mock mode
# live Vexcel: set USE_MOCK_DATA=false and VEXCEL_API_KEY in backend/.env (see docs/DEMO_RUNBOOK.md)
venv/bin/uvicorn app.main:app --reload
```

**Frontend** (http://localhost:3000), in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend calls relative URLs; `next.config.ts` proxies `/api/v1`, `/static` and `/health` to
`API_ORIGIN` (default `http://localhost:8000`). To point it elsewhere, set `API_ORIGIN` in
`frontend/.env.local`.

**Try it:** choose *Restaurant*, type "40 seats, kitchen needed, 2 bathrooms", keep *Houston, TX*,
click **Find spaces**, then **Select all** and **Compare 5 selected**. Expected result: 1903 Yale Street
ranks #1 (score 100, first-year $93.2k-$104.5k), 801 St Emanuel Street #2, 3701 Kirby Drive and 240 W
19th Street are weak fits, and 4720 Washington Avenue is disqualified by its "no food service" deed
restriction. Offline dataset: city *Austin*, **Use example**, Compare 4 → 456 Oak Avenue #1, 789 Congress
Avenue disqualified on zoning. The full script is in [docs/DEMO_RUNBOOK.md](docs/DEMO_RUNBOOK.md).

Quick API check:

```bash
curl localhost:8000/health
curl -X POST localhost:8000/api/v1/analyze -H 'Content-Type: application/json' -d '{
  "business_profile": {"type": "restaurant", "details": "40 seats, kitchen needed, 2 bathrooms", "city": "Houston", "state": "TX"},
  "property_ids": ["property-hou-01", "property-hou-02", "property-hou-03", "property-hou-04", "property-hou-05"]}'
```

## Tests

```bash
cd backend && venv/bin/pytest -q     # 152 tests
cd frontend && npm test              # Vitest, 49 tests
cd frontend && npm run lint          # ESLint
cd frontend && npm run e2e           # Playwright, 6 tests: Austin + Houston flows and error state, desktop and 375px mobile
```

See [docs/TEST_PLAN.md](docs/TEST_PLAN.md) for what each suite covers and the manual checks.

## Configuration

| File | What it controls |
|---|---|
| `backend/criteria.yaml` | Criteria registry: weights, hard blocks, evaluators, missing-data policies, citations |
| `backend/config/costs.yaml` | Cost bands, soft costs, ranking horizon and minimum fit score |
| `backend/config/business_types.yaml` | Business profiles (capacity unit, occupant load, parking guideline, HVAC, electrical, sprinkler trigger) |
| `backend/config/jurisdictions.yaml` | Local rules: Houston (no zoning + deed restrictions, parking ratios, market-based areas, plumbing code), Austin (zoning use table, parking note), generic default |
| `backend/fixtures/` | Listings and Matterport / Vexcel facts for mock mode (Houston aerial facts are Vexcel snapshots) |
| `.env.example` → `backend/.env` | API keys, mock mode, DB path, CORS. See [docs/SECURITY_AND_ENV.md](docs/SECURITY_AND_ENV.md) |

All YAML files are re-read when they change on disk, so no restart is needed.

## Repository layout

```
.
├── .env.example               # every env var the code reads (placeholders)
├── CLAUDE.md                  # project rules for Claude Code
├── prompts/                   # phase prompts 00-05 + scale-criteria
├── docs/                      # design docs (index below)
├── backend/
│   ├── requirements.txt  pytest.ini
│   ├── criteria.yaml          # criteria registry
│   ├── config/                # business_types.yaml, costs.yaml, jurisdictions.yaml
│   ├── fixtures/              # properties.json (CoStar-shaped), observations.json (Matterport/Vexcel facts)
│   ├── scripts/               # snapshot_vexcel.py (live Vexcel facts → fixtures, cache pre-warm)
│   ├── static/                # placeholder SVGs (aerials/, floorplans/, properties/) + vexcel-cache/ (gitignored)
│   ├── app/
│   │   ├── main.py            # FastAPI app, CORS, routers, /static mount
│   │   ├── config.py          # env settings + hot-reloading YAML loader
│   │   ├── db.py              # SQLModel run history (analysis_runs)
│   │   ├── models/            # analysis_result, business_profile, criterion, property
│   │   ├── providers/         # costar_provider, matterport_provider, vexcel_provider, _fixtures
│   │   ├── routers/           # health, business_types, criteria, properties, analyze, analyses
│   │   └── services/          # requirements_parser, criteria_manager, evaluators,
│   │                          # compliance_engine, cost_engine, scoring, agent_orchestrator
│   └── tests/                 # pytest suites + conftest.py
└── frontend/
    ├── next.config.ts         # rewrites to API_ORIGIN
    ├── vitest.config.mts
    ├── app/                   # layout, page (home), properties/, analysis/[id]/
    ├── components/            # form, cards, tables, analysis/*, ui/*
    ├── lib/                   # api.ts, types.ts, format.ts, overlay.ts, useAsync.ts
    └── test/                  # Vitest specs + fixtures
```

## Documentation

| Doc | Topic |
|---|---|
| [PROJECT_BRIEF](docs/PROJECT_BRIEF.md), [PRD](docs/PRD.md) | Problem, users, requirements |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Modules and data flow |
| [API_CONTRACT](docs/API_CONTRACT.md) | REST endpoints and shapes (source of truth) |
| [BACKEND](docs/BACKEND.md), [DATA_MODELS](docs/DATA_MODELS.md) | Backend files and schemas |
| [AGENT_ORCHESTRATION](docs/AGENT_ORCHESTRATION.md) | The five-step analysis pipeline |
| [COMPLIANCE_AGENT](docs/COMPLIANCE_AGENT.md), [COMPLIANCE_RULE_SOURCES](docs/COMPLIANCE_RULE_SOURCES.md) | Evaluators, statuses, citations |
| [COST_ENGINE](docs/COST_ENGINE.md) | Cost formula and worked example |
| [CRITERIA_REGISTRY](docs/CRITERIA_REGISTRY.md) | Registry fields, adding criteria and evaluators |
| [FRONTEND_DESIGN](docs/FRONTEND_DESIGN.md), [VISION_OVERLAYS](docs/VISION_OVERLAYS.md) | Routes, components, theme, overlays |
| [INTEGRATIONS](docs/INTEGRATIONS.md), [SECURITY_AND_ENV](docs/SECURITY_AND_ENV.md) | Live Vexcel, mock CoStar / Matterport, env vars, key handling |
| [TEST_PLAN](docs/TEST_PLAN.md), [DEMO_RUNBOOK](docs/DEMO_RUNBOOK.md) | Testing and the live demo |
| [BUILD_PLAN](docs/BUILD_PLAN.md), [DECISIONS_AND_RISKS](docs/DECISIONS_AND_RISKS.md), [SPONSOR_STRATEGY](docs/SPONSOR_STRATEGY.md) | Status, trade-offs, sponsors |

## Disclaimer

Cost figures are preliminary planning ranges from fixed bands, not contractor quotes. Compliance
results are decision support only; verify with the city and a licensed professional. Houston listings
are samples at real buildings: rent, size and interior details are illustrative. Aerial imagery
© Vexcel Imaging US, Inc.; cached imagery is licensed and not part of this repository.
