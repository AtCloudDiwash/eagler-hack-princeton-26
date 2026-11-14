# Build Plan (36 hours): status

Phases follow `prompts/`. Each was executed from the repo root and builds on the previous one.

| Phase | Prompt | Status | Delivered |
|---|---|---|---|
| 00 | `00-bootstrap.md` | Done | Monorepo, docs skeleton, `.gitignore`, `.env.example`, backend models/providers/config |
| 01 | `01-backend-skeleton.md` | Done | FastAPI app, `/health`, routers for business types, criteria, properties, analyze, analyses; CORS; static media |
| 02 | `02-agent-workflow.md` | Done | Five-step orchestrator, requirements parser (regex + optional Claude), evaluator registry, compliance engine, cost engine, scoring, landlord questions + letter, SQLite run history |
| 03 | `03-frontend-skeleton.md` | Done | Next.js 16 App Router: profile form, property selection, analysis report, dark navy/cyan theme, Vitest tests |
| 04 | `04-integrations.md` | Done | Live CoStar / Matterport / Vexcel adapters behind `USE_MOCK_DATA` + keys with fixture fallback; aerial and floor-plan overlays |
| scale | `scale-criteria.md` | Done | `window_visibility` added via `criteria.yaml` + one evaluator; test proves config-only scaling |
| 05 | `05-demo-polish.md` | In progress | See below |

## Phase 05 checklist

- [x] UI polish: loading overlay for analysis, info-icon source tooltips, N/A placeholders, responsive layout
- [x] Every backend field shown in the UI (costs, line items, compliance, observations, assumptions, letter)
- [x] Mock demo scenario + saved API response fixture (`frontend/test/fixtures/analysis.json`)
- [x] All tests green (backend 88, frontend 28, Playwright 4); lint clean
- [x] Criteria scaling test (`test_adding_a_criterion_via_config_changes_results`)
- [x] Min-score ranking gate (`ranking.min_score`, "weak fit" badge)
- [x] Playwright E2E for the demo flow (desktop + 375px mobile + failure state)
- [x] Documentation finalized against the code (this pass): README, `.env.example`, all of `docs/`
- [ ] Final dry run of [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) on the presentation machine
- [ ] Clean up and commit ("Final polish before demo")

## Remaining / stretch (only if time allows)

- Real CoStar / Vexcel endpoint paths once sponsor docs or keys arrive (mapping functions are ready).
- Peri validation: record a small business owner interview and add the quote to the pitch
  ([SPONSOR_STRATEGY.md](SPONSOR_STRATEGY.md)).
- A second jurisdiction in `jurisdictions.yaml`.
- Optional AWS deployment (backend container + static frontend).
- Small code issues found during the docs pass (see [DECISIONS_AND_RISKS.md](DECISIONS_AND_RISKS.md#known-issues)).
