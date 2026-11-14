# Backend

Python 3.12 (3.10+ works), FastAPI, Pydantic v2, SQLModel on SQLite. All business endpoints are
under `/api/v1`. Run from `backend/`: `venv/bin/uvicorn app.main:app --reload`.

## Directory structure (`backend/`)

```
backend/
├── requirements.txt         pinned deps (fastapi, uvicorn, pydantic, PyYAML, python-dotenv,
│                            sqlmodel, SQLAlchemy, httpx, anthropic, pytest)
├── pytest.ini               testpaths=tests, pythonpath=.
├── criteria.yaml            criteria registry (CRITERIA_PATH overrides)
├── config/
│   ├── business_types.yaml  restaurant, dental_clinic profiles
│   ├── costs.yaml           cost item bands, soft costs, ranking settings, disclaimer
│   └── jurisdictions.yaml   default + houston-tx (no zoning, deed restrictions, parking ratios and
│                            market-based areas, 2021 UPC) + austin-tx (zoning use table, parking note)
├── fixtures/
│   ├── properties.json      5 Houston sample listings + 4 Austin listings (CoStar-shaped)
│   └── observations.json    Matterport ("interior") and Vexcel ("aerial") facts per property; Houston
│                            aerial facts are snapshots of live Vexcel responses
├── scripts/
│   └── snapshot_vexcel.py   live Vexcel facts → observations.json (--only, --dry-run, --from-cache)
├── static/                  served at /static: placeholder SVGs (aerials/, floorplans/, properties/)
│   └── vexcel-cache/        cached live Vexcel imagery + JSON per property (gitignored, licensed)
├── app/
│   ├── main.py
│   ├── config.py
│   ├── db.py
│   ├── models/              analysis_result.py, business_profile.py, criterion.py, property.py
│   ├── providers/           _fixtures.py, costar_provider.py, matterport_provider.py, vexcel_provider.py
│   ├── routers/             health.py, business_types.py, criteria.py, properties.py, analyze.py, analyses.py
│   └── services/            requirements_parser.py, criteria_manager.py, evaluators.py,
│                            compliance_engine.py, cost_engine.py, scoring.py, agent_orchestrator.py
└── tests/                   conftest.py + 9 test modules + fixtures/ (see TEST_PLAN.md)
```

## Endpoints

| Method | Path | Router | Notes |
|---|---|---|---|
| GET | `/health` | `health.py` | `{status, mode: {costar, matterport, vexcel, parser}}` (live Vexcel: `vexcel: "live"`) |
| GET | `/api/v1/business-types` | `business_types.py` | From `business_types.yaml` |
| GET | `/api/v1/criteria?business_type=&city=&state=` | `criteria.py` | Filtered registry; unknown type → 400 |
| GET | `/api/v1/properties?business_type=&city=&state=&min_size=&max_size=&budget=` | `properties.py` | `city` matches name or ZIP; `budget` = max monthly rent |
| POST | `/api/v1/analyze` | `analyze.py` | Runs the pipeline and stores the run |
| GET | `/api/v1/analyses?limit=20` | `analyses.py` | History, newest first (`limit` 1-100) |
| GET | `/api/v1/analyses/{id}` | `analyses.py` | Stored `AnalyzeResponse` as originally returned, re-validated so fields added later get defaults (`min_score` 0, `weak_fit` false, `aerial_source` "placeholder", ...); 404 if unknown |

Shapes: [API_CONTRACT.md](API_CONTRACT.md).

## Modules and key functions

### `app/config.py`
- `settings` (`Settings`): API keys (placeholders starting with `your_` count as unset), base URLs,
  `provider_timeout_seconds`, `database_url` (relative SQLite paths resolved against `backend/`),
  `force_mock` (`USE_MOCK_DATA`, default true), `criteria_path`, `cors_origins`, `anthropic_model`.
- `settings.provider_mode(key)`: `"live"` only when mock mode is off and that key is set.
- `settings.parser_mode`, `settings.mode_summary`: what `/health` reports.
- `load_yaml(path)`: re-reads a YAML file only when its mtime/size changes (hot reload).
- `business_types()`, `cost_config()`, `jurisdiction_for(city, state)` (`"<city>-<state>"` key,
  merged over `default`; `rules["key"]` tells which matched).

### `app/db.py`
- `AnalysisRun` table `analysis_runs` (see [DATA_MODELS.md](DATA_MODELS.md)).
- `init_db()` (called in the app lifespan), `save_run(response)`, `list_runs(limit)`, `get_run(id)`.

### `app/providers/`
- `costar_provider`: `all_properties()`, `search_properties(city, state, min_size, max_size, max_rent)`,
  `get_property(id)`, `map_costar_listing(row)` (tolerant field mapping for live payloads).
- `matterport_provider`: `get_interior(prop)` → `{floor_plan_url, matterport_embed_url, observations}`;
  `get_interior_images(property_id, matterport_url)`.
- `vexcel_provider`: `get_aerial(prop, force_refresh=False)` → `{aerial_url, oblique_url, aerial_source,
  aerial_attribution, observations, live_observations, errors}`; `get_aerial_image(prop)`; `fetch_live`
  (three parallel calls with `X-API-KEY`, disk cache, permanent/transient failure memory);
  `normalize_property_extract`, `footprint_box`, `read_cached_property`, `is_snapshot_fact`.
- `_fixtures.load_fixture(name)`: cached JSON loader for `backend/fixtures/`.

Mock vs live behavior: [INTEGRATIONS.md](INTEGRATIONS.md).

### `app/services/`
| Module | Key functions |
|---|---|
| `requirements_parser.py` | `parse_requirements(profile) -> (Requirements, "regex"\|"claude")`, `regex_extract`, `claude_extract`, `build_requirements`, `get_business` (raises `UnknownBusinessType`), `occupant_load`, `restrooms_for`; parking minimums: `code_parking_minimum`, `exempt_parking_area`, `property_parking_requirement` (`ParkingMinimum`) |
| `criteria_manager.py` | `load_criteria(path=None)` (validates, rejects duplicates, raises `CriteriaConfigError`), `applicable_criteria(business_type, city, state)`, `get_criterion`, `criteria_by_id` |
| `evaluators.py` | `@evaluator(name, fallback=None)` registry, `get_evaluator`, `registered_evaluators`; `EvalContext`, `EvalOutcome`, `CostNeed`; the 12 evaluators listed in [COMPLIANCE_AGENT.md](COMPLIANCE_AGENT.md) |
| `compliance_engine.py` | `run_compliance(...) -> ComplianceReport`, `evaluate_criterion` (incl. the "verify" rule), `build_inputs` (per-property parking requirement); simple helpers `check_parking`, `check_ada` |
| `cost_engine.py` | `estimate(needs, prop, business) -> CostEstimate`, `price_item`, `merge_needs`; helpers `estimate_cost`, `estimate_kitchen_cost` |
| `scoring.py` | `weighted_score(results)`, `STATUS_SCORE` |
| `agent_orchestrator.py` | `analyze_properties(profile, properties)`, `analyze_property`, `gather_observations`, `landlord_questions`, `draft_landlord_request`, `rank_results` |

Pipeline walkthrough: [AGENT_ORCHESTRATION.md](AGENT_ORCHESTRATION.md).

## Error handling

- Pydantic validation → 422 (e.g. empty `property_ids`, missing `city`, `state` shorter than 2 chars).
- Unknown business type → 400; unknown property or analysis id → 404.
- Malformed `criteria.yaml` → 500 `{"detail": "Criteria registry error: criteria.yaml entry #3 (id 'x') is invalid: ..."}`.
- An evaluator that raises, or an `evaluator` name that is not registered, produces an UNKNOWN
  result with a note. It never fails the request.
- Live provider errors are logged (key redacted) and fall back to fixtures, per item for Vexcel.

## Logging

On startup the app logs the provider/parser modes and the DB URL (keys are never logged). Provider
and Claude fallbacks log a warning, e.g. "Vexcel property for property-x unavailable: outside the
Vexcel account geofence (403); using fallback".
