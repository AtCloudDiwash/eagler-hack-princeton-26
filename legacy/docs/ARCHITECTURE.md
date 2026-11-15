# Architecture

Monorepo with two apps:

- **frontend/**: Next.js 16 App Router client (React 19, TypeScript, Tailwind v4).
- **backend/**: FastAPI service with a five-step agent pipeline, YAML-driven criteria/costs/jurisdiction
  rules, data providers (live Vexcel; mock CoStar and Matterport), an optional local LLM (Ollama) for
  requirements parsing and a grounded ranking summary, and SQLite run history.

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
              └─ /static (StaticFiles)      placeholder aerials / floor plans / listing photos,
                                            plus cached live Vexcel imagery (/static/vexcel-cache/)

           providers/vexcel_provider.py ──(X-API-KEY, live mode only)──► api.vexcelgroup.com/v2
              ortho + oblique + property/extract, cached in backend/static/vexcel-cache/ (gitignored)

           services/llm.py ──(HTTP, localhost only)──► Ollama (:11434)  qwen3:8b
              GET /api/tags (availability), POST /api/chat (JSON-schema format), /api/generate (warm-up)
              [LLM_PROVIDER=anthropic: Anthropic Messages API instead; none: no LLM]
```

The browser never talks to Vexcel or the LLM: the backend downloads and caches imagery and serves it from
`/static`, so the key stays server-side, and only the backend calls Ollama.

## Analysis data flow (POST /api/v1/analyze)

```
AnalyzeRequest {business_profile, property_ids}
  │  routers/analyze.py: validate business type (400), dedupe ids, load each Property (404 if unknown)
  ▼
1. requirements_parser.parse_requirements      LLM (Ollama qwen3:8b) merged over regex; regex alone if
  │                                            the LLM is down / fails → Requirements + assumptions
  │
  │  for each property:  agent_orchestrator.analyze_property
  ▼
2. gather_observations (vision agent)          CoStar listing + Matterport interior + Vexcel aerial
  │                                            (live: ortho, oblique, AI facts from cache/API)
  │                                            → observations: {fact: Evidence}, Media URLs
3. compliance_engine.run_compliance            criteria_manager.applicable_criteria → evaluators.*
  │                                            + jurisdiction rules (zoning mode, use restrictions,
  │                                              parking ratios / exempt areas, plumbing code)
  │                                            → CriterionResult[], cost needs, questions, disqualifiers, score
4. cost_engine.estimate                        cost needs × costs.yaml bands → fit-out, TI, build-out,
  │                                            cost to open, first-year cost (all ranges)
5. landlord_questions / draft_landlord_request → questions + letter
  ▼
rank_results  (qualifying by first-year cost → weak fit (score < min_score) → disqualified; ties by score)
  ▼
6. ranking_summary.summarize_ranking           one LLM call over a digest of the finished ranking →
  │                                            guardrail (unknown $ / score / id → reject) → ai_summary | null
  ▼
AnalyzeResponse ──► db.save_run (stored verbatim) ──► JSON to the browser ──► router.push(/analysis/{id})
```

The report page then loads `GET /api/v1/analyses/{id}`, so every report URL is shareable and
reloadable.

## Backend modules

| Layer | Module | Responsibility |
|---|---|---|
| Entry | `app/main.py` | App, CORS (`CORS_ORIGINS`), routers, `/static`, `CriteriaConfigError` → 500 with a clear message, DB init and background Ollama warm-up on startup |
| Config | `app/config.py` | Env settings, provider modes, mtime-cached YAML loader (`load_yaml`), `jurisdiction_for(city, state)` (Houston, Austin, default) |
| Persistence | `app/db.py` | `AnalysisRun` SQLModel table, `save_run`, `list_runs`, `get_run` |
| Schemas | `app/models/*` | Pydantic request/response models (see [DATA_MODELS.md](DATA_MODELS.md)) |
| Providers | `app/providers/*` | CoStar listings and Matterport interior (mock), Vexcel imagery + AI facts (live with disk cache and per-item fallback); mock by default |
| Scripts | `scripts/snapshot_vexcel.py`, `scripts/llm_live_check.py` | Snapshot live Vexcel facts into `fixtures/observations.json` (also pre-warms the cache; `--from-cache` re-normalizes offline); run the demo against a live Ollama with timings |
| Services | `app/services/*` | Parser, LLM provider (`llm.py`), grounded ranking summary (`ranking_summary.py`), criteria registry, evaluator registry, compliance engine, cost engine, scoring, orchestrator |

## Frontend modules

| Layer | Files |
|---|---|
| Routes | `app/page.tsx` (home), `app/properties/` (`PropertiesView`), `app/analysis/[id]/` (`AnalysisView`) |
| Data | `lib/api.ts` (typed fetch client + `ApiError`), `lib/useAsync.ts`, `lib/types.ts` |
| Presentation | `components/*`, `components/analysis/*`, `components/ui/*` |
| Helpers | `lib/format.ts` (ranges, currency, N/A, parking source labels, parser / LLM labels), `lib/overlay.ts` (evidence boxes, footprint) |

Details: [FRONTEND_DESIGN.md](FRONTEND_DESIGN.md).

## Design principles

- **Config over code.** Criteria, cost bands, business types and jurisdiction rules are YAML and
  hot-reload. The UI renders whatever the registry returns.
- **Deterministic core.** Scores, costs, compliance statuses and ranks come from rules. Image analysis is
  Vexcel's AI (consumed as facts). Our LLM (local Ollama by default) only extracts requirement fields
  (regex fallback) and explains the finished ranking (guardrailed, `null` fallback).
- **Never break the demo.** Mock fixtures are the default; live provider failures fall back to
  fixtures per item; a warm Vexcel cache needs no network; a broken or unknown evaluator yields UNKNOWN
  instead of a 500.
- **Ranges, not point estimates**, plus an explicit assumptions list on every result.

## Not built (by design for the MVP)

Background jobs/polling (analysis is synchronous: milliseconds without the LLM, about 7 s with the
warm local LLM), response caching beyond the YAML/fixture/
Vexcel caches, our own image detection (aerial facts come from Vexcel's AI; interior facts are
Matterport-shaped fixtures), live CoStar / Matterport, geocoding, and authentication.
