# Build Plan (36 hours): status

Phases follow `prompts/`. Each was executed from the repo root and builds on the previous one.

| Phase | Prompt | Status | Delivered |
|---|---|---|---|
| 00 | `00-bootstrap.md` | Done | Monorepo, docs skeleton, `.gitignore`, `.env.example`, backend models/providers/config |
| 01 | `01-backend-skeleton.md` | Done | FastAPI app, `/health`, routers for business types, criteria, properties, analyze, analyses; CORS; static media |
| 02 | `02-agent-workflow.md` | Done | Five-step orchestrator, requirements parser (regex + optional Claude), evaluator registry, compliance engine, cost engine, scoring, landlord questions + letter, SQLite run history |
| 03 | `03-frontend-skeleton.md` | Done | Next.js 16 App Router: profile form, property selection, analysis report, dark navy/cyan theme, Vitest tests |
| 04 | `04-integrations.md` | Done | **Live Vexcel** (ortho, oblique-north, `/property/extract` AI facts, disk cache, per-item fallback, snapshot script); CoStar / Matterport adapters behind keys with fixture fallback; aerial footprint and floor-plan overlays |
| scale | `scale-criteria.md` | Done | `window_visibility` added via `criteria.yaml` + one evaluator; later `roof_condition` the same way; test proves config-only scaling |
| 05 | `05-demo-polish.md` | In progress | See below |

## Phase 05 checklist

- [x] UI polish: loading overlay, info-icon source tooltips, N/A placeholders, responsive layout
- [x] Every backend field shown in the UI (costs, line items, compliance, observations, assumptions, letter)
- [x] Min-score ranking gate (`ranking.min_score`, now 55) with "Weak fit" badge
- [x] Playwright E2E: Austin and Houston flows, desktop + 375px mobile, failure state
- [x] **Houston demo city**: 5 sample listings at real buildings, Houston rules in `jurisdictions.yaml`
      (no zoning + deed restrictions, §26-492 parking ratios, §26-471 market-based areas, 2021 UPC)
- [x] **Live Vexcel integration** with "Live · Vexcel" badge, attribution, Top-down / Angled tabs,
      square aerial frame, footprint overlay, live evidence dots; mock mode replays snapshot facts
- [x] New rules: `roof_condition` + `roof_repair`; parking estimate from paved area; HVAC prorated to
      the suite share with "verify with landlord"; use-restriction hard block
- [x] "Sample listing" badge and use-restriction line on property cards
- [x] All tests green (backend 152, frontend 49, Playwright 6); lint clean
- [x] Live mode verified end to end (ranking matches mock, all 5 Houston results `vexcel-live`,
      9-10 live facts each, cached images served, key absent from logs)
- [x] Documentation re-synced to the code (this pass): README, `.env.example`, all of `docs/`
- [ ] Pre-warm the Vexcel cache and dry-run [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) on the presentation machine
- [ ] Clean up and commit ("Final polish before demo")

## Remaining / stretch (only if time allows)

- Real CoStar listings once access arrives (replaces the sample listings; `map_costar_listing` is ready).
- Matterport tour links for the listings (the iframe viewer is ready; set `matterport_url`).
- Peri validation: record a small business owner interview and add the quote to the pitch
  ([SPONSOR_STRATEGY.md](SPONSOR_STRATEGY.md)).
- Known issues in [DECISIONS_AND_RISKS.md](DECISIONS_AND_RISKS.md#known-issues) (hand-made parking boxes
  on live imagery, Austin-specific grease citation).
- Optional AWS deployment (backend container + static frontend; check Vexcel terms for cached imagery).
