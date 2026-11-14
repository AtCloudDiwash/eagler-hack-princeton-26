# Key Decisions and Risks

## Decisions

### Architecture and stack
- **Next.js 16 App Router** (`frontend/app/`), not the pages router, with React 19 and TypeScript.
- **Tailwind CSS v4 with hand-rolled components** (`components/ui/`). We did not use shadcn: a handful
  of small components was faster than adopting a library, and theme tokens live in `@theme` in
  `app/globals.css` (no `tailwind.config.js`).
- **Relative API URLs + Next rewrites.** The browser calls `/api/v1/...`, `/static/...` and `/health`;
  `next.config.ts` proxies them to `API_ORIGIN` (default `http://localhost:8000`). No backend URL is baked
  into client code, and no `NEXT_PUBLIC_` variable is needed. CORS (`CORS_ORIGINS`) is still enabled for
  direct calls.
- **FastAPI + Pydantic v2** with a synchronous pipeline. A 4-property analysis runs in milliseconds, so
  there are no background jobs or polling.
- **Vitest + React Testing Library** for the frontend (not Jest), plus **Playwright** E2E.

### Data and persistence
- **Mock mode by default** (`USE_MOCK_DATA=true`). A provider goes live only when mock mode is off and
  its key is set. Any live failure falls back to the fixtures, so the demo cannot be broken by an
  integration. Matterport/Vexcel *facts* always come from fixtures; only image URLs go live.
- **SQLite run history via SQLModel** (`DATABASE_URL`, default `sqlite:///./turnkey.db` resolved
  relative to `backend/`). Every `/analyze` response is stored verbatim, which gives shareable,
  reloadable `/analysis/{id}` URLs and a "Recent analyses" list. There are no migrations; the DB is
  disposable.

### Agents and rules
- **Requirements parser:** the regex parser is always available. If `ANTHROPIC_API_KEY` is set, Claude
  (`ANTHROPIC_MODEL`, default `claude-haiku-5-5`) is tried first with schema-constrained JSON, an 8 s
  timeout and no retries. Its validated fields merge over the regex result, and any error, refusal or
  timeout falls back to regex. This is the only LLM in the system.
- **Deterministic cost bands, no ML, ranges only** (`costs.yaml`). Permits are always included.
  Soft costs (general conditions, contingency, permits) are listed in `line_items` / `breakdown`, so
  they sum to `fit_out_estimate`.
- **Ranking with a minimum fit score** (replaces pure first-year-cost ranking): qualifying spaces
  (score >= `ranking.min_score`, 25) by first-year cost, then **weak fit** spaces (score below the gate),
  then disqualified spaces. Ties are broken by score. Rationale: a space that fails almost every
  check should not outrank a real fit just because its numbers look cheaper (property-321 in the demo).
  Exposed as `AnalysisResult.weak_fit` and `AnalyzeResponse.min_score`. Runs stored before the gate
  existed read back with `min_score: 0` and `weak_fit: false`.
- **Criteria registry in YAML, hot-reloaded.** Adding or re-weighting a criterion is a config edit.
  New logic is one decorated evaluator function. The UI never hard-codes criterion ids.
- **Hard block only on a definitive failure.** Missing data never disqualifies.
- **Evaluator specifics:**
  - `window_visibility` is restaurant-only. Below the threshold it is **RISK** (scored 0), where the
    scale-criteria prompt suggested UNKNOWN. With no window data it is ignored (not scored).
  - Missing sprinklers where IBC §903.2 requires them are **priced as a retrofit, not disqualifying**
    (sprinklers can almost always be added). `fire_safety` has weight 0 and never reports a definitive
    failure, so **zoning is currently the only practical hard block**.
  - HVAC need = **max**(seat/space-need based tons from the parser, the listing's floor area ÷ sq ft per ton).
  - Parking is compared with the business's need (stated or guideline), not a code minimum. Austin
    removed parking minimums in 2023.
- **One real jurisdiction (Austin, TX)** with a simplified zoning use table. Other cities use the generic
  default and get an explicit "model codes used" assumption.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Sponsor APIs unavailable or endpoints unknown | Mock fixtures are the default; live adapters with tolerant mapping and fixture fallback |
| Zoning / code rules are simplified or wrong for a parcel | Citations on every result, "(simplified)" labels, UNKNOWN when not in the table, disclaimer, landlord questions |
| Cost estimates taken as quotes | Ranges only, assumptions listed, disclaimer on every report and in the letter |
| Vision facts are mocked | Facts carry confidence; < 0.7 is flagged "verify on site"; overlays are illustrative |
| Claude returns bad output or is slow | Strict schema, value range checks, 8 s timeout, regex fallback; tests use a fake client |
| Broken YAML during a live edit | Validation error names the entry; malformed registry → clear 500; unknown evaluator → UNKNOWN |
| Live demo failure | Deterministic mock data, Playwright E2E, pre-opened report tab, curl fallback, recording ([DEMO_RUNBOOK.md](DEMO_RUNBOOK.md)) |
| Stored analyses readable by anyone with the id | Acceptable for a local demo; add auth before deployment |
| Imagery licensing | Only placeholder SVGs are committed |

## Known issues

Found while writing the docs.

1. **Zoning fallback citation is Austin-specific** (open). `criteria.yaml` `zoning_use.source` cites the
   Austin LDC while applying to ALL jurisdictions. Non-Austin cities return UNKNOWN with the
   jurisdiction's `zoning_source` (null), so the Austin citation shows as the fallback.
2. **Unused config** (open). `GEOCODING_API_KEY` and the `jurisdictions.yaml` keys `building_code`,
   `health_code` and `parking_minimums` are loaded but not read by any code.
3. **`/health` vs `mode.parser`** (intended). `/health` reports the *configured* parser (`claude` if a key
   is set), while `AnalyzeResponse.mode.parser` reports the parser *actually used*, which can be `regex`
   after a fallback. Documented in API_CONTRACT.md.

Fixed: the dental fallback unit in `BusinessProfileForm.tsx` now says "chairs" (matching
`business_types.yaml`), and the State input is `required` with `minLength={2}`, so the form can no longer
submit a profile that `POST /analyze` rejects.
