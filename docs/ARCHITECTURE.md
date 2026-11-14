# Architecture

Monorepo with two apps:

- **frontend/**: Next.js 16 App Router client (React 19, TypeScript, Tailwind v4).
- **backend/**: FastAPI service with a five-step agent pipeline, YAML-driven criteria/costs, mock
  data providers and SQLite run history.

They talk over versioned REST (`/api/v1/...`, see [API_CONTRACT.md](API_CONTRACT.md)).

## System diagram

```
Browser ──► Next.js dev server (:3000)
              │  pages: /  /properties  /analysis/[id]
              │  lib/api.ts calls relative URLs
              │  next.config.ts rewrites /api/v1/*, /static/*, /health ──► API_ORIGIN
              ▼
           FastAPI (:8000)  app/main.py
              ├─ routers/health.py          GET /health
              ├─ routers/business_types.py  GET /api/v1/business-types   ◄── config/business_types.yaml
              ├─ routers/criteria.py        GET /api/v1/criteria         ◄── criteria.yaml (criteria_manager)
              ├─ routers/properties.py      GET /api/v1/properties       ◄── providers/costar_provider
              ├─ routers/analyze.py         POST /api/v1/analyze ──► services/agent_orchestrator ──► db.save_run
              ├─ routers/analyses.py        GET /api/v1/analyses[/{id}]  ◄── db.py (SQLite analysis_runs)
              └─ /static (StaticFiles)      placeholder aerials / floor plans / listing photos
```

## Analysis data flow (POST /api/v1/analyze)

```
AnalyzeRequest {business_profile, property_ids}
  │  routers/analyze.py: validate business type (400), dedupe ids, load each Property (404 if unknown)
  ▼
1. requirements_parser.parse_requirements      regex (+ optional Claude) → Requirements + assumptions
  │
  │  for each property:  agent_orchestrator.analyze_property
  ▼
2. gather_observations (vision agent)          CoStar listing + Matterport interior + Vexcel aerial
  │                                            → observations: {fact: Evidence}, Media URLs
3. compliance_engine.run_compliance            criteria_manager.applicable_criteria → evaluators.*
  │                                            → CriterionResult[], cost needs, questions, disqualifiers, score
4. cost_engine.estimate                        cost needs × costs.yaml bands → fit-out, TI, build-out,
  │                                            cost to open, first-year cost (all ranges)
5. landlord_questions / draft_landlord_request → questions + letter
  ▼
rank_results  (qualifying by first-year cost → weak fit (score < min_score) → disqualified; ties by score)
  ▼
AnalyzeResponse ──► db.save_run (stored verbatim) ──► JSON to the browser ──► router.push(/analysis/{id})
```

The report page then loads `GET /api/v1/analyses/{id}`, so every report URL is shareable and
reloadable.

## Backend modules

| Layer | Module | Responsibility |
|---|---|---|
| Entry | `app/main.py` | App, CORS (`CORS_ORIGINS`), routers, `/static`, `CriteriaConfigError` → 500 with a clear message, DB init on startup |
| Config | `app/config.py` | Env settings, provider modes, mtime-cached YAML loader (`load_yaml`), `jurisdiction_for(city, state)` |
| Persistence | `app/db.py` | `AnalysisRun` SQLModel table, `save_run`, `list_runs`, `get_run` |
| Schemas | `app/models/*` | Pydantic request/response models (see [DATA_MODELS.md](DATA_MODELS.md)) |
| Providers | `app/providers/*` | CoStar listings, Matterport interior, Vexcel aerial; mock by default, live with fallback |
| Services | `app/services/*` | Parser, criteria registry, evaluator registry, compliance engine, cost engine, scoring, orchestrator |

## Frontend modules

| Layer | Files |
|---|---|
| Routes | `app/page.tsx` (home), `app/properties/` (`PropertiesView`), `app/analysis/[id]/` (`AnalysisView`) |
| Data | `lib/api.ts` (typed fetch client + `ApiError`), `lib/useAsync.ts`, `lib/types.ts` |
| Presentation | `components/*`, `components/analysis/*`, `components/ui/*` |
| Helpers | `lib/format.ts` (ranges, currency, N/A), `lib/overlay.ts` (evidence boxes) |

Details: [FRONTEND_DESIGN.md](FRONTEND_DESIGN.md).

## Design principles

- **Config over code.** Criteria, cost bands, business types and jurisdiction rules are YAML and
  hot-reload. The UI renders whatever the registry returns.
- **Deterministic core.** Scores, costs and compliance statuses come from rules. The only LLM use is
  the optional Claude requirements parser, and it always falls back to regex.
- **Never break the demo.** Mock fixtures are the default; live provider failures fall back to
  fixtures; a broken or unknown evaluator yields UNKNOWN instead of a 500.
- **Ranges, not point estimates**, plus an explicit assumptions list on every result.

## Not built (by design for the MVP)

Background jobs/polling (analysis is synchronous and fast), response caching beyond the YAML/fixture
caches, real image detection (vision facts come from fixtures), geocoding, and authentication.
