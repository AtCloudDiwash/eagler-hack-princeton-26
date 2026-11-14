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
- **FastAPI + Pydantic v2** with a synchronous pipeline. A 5-property analysis runs in milliseconds
  (mock or warm Vexcel cache), so there are no background jobs or polling.
- **Vitest + React Testing Library** for the frontend (not Jest), plus **Playwright** E2E.

### Demo city and data
- **Houston, TX is the demo city.** The sponsor's Vexcel key is geofenced to Los Angeles and Houston,
  and Houston's rules (no zoning, enforceable deed restrictions, parking minimums with market-based
  exemptions) make a stronger compliance story. The Austin listings and rules stay as an **offline
  dataset** (mock mode; the E2E suite covers both cities).
- **Sample listings at real buildings.** Without CoStar access, the 5 Houston listings are hand-made
  records at real addresses and coordinates (`listing_source: "sample"`): rent, size, previous use, TI,
  interior facts and striped parking counts are illustrative; the Vexcel data is real. The UI labels
  them with a "Sample listing" badge rather than passing them off as market data.
- **Mock mode by default** (`USE_MOCK_DATA=true`). A provider goes live only when mock mode is off and
  its key is set. Any live failure falls back to the fixtures.
- **Live Vexcel, mock CoStar / Matterport.** Vexcel is a real integration (ortho, oblique-north,
  `/property/extract`); CoStar and Matterport adapters exist but stay mock without keys.
- **Mock mode reproduces live mode.** The Houston aerial facts in `observations.json` are snapshots of
  the real `/property/extract` responses (`scripts/snapshot_vexcel.py`), so mock and live rank
  identically and the demo has an offline fallback with the same numbers.
- **Server-side Vexcel cache** (`backend/static/vexcel-cache/`, gitignored): the key never reaches the
  browser (header-only, backend-only), repeat analyses make no calls, a warm cache works offline, and
  licensed imagery is never committed. Permanent failures (403/404) are remembered on disk, transient
  ones for 10 minutes in memory. Each item (ortho, oblique, facts) falls back independently.
- **Oblique product `oblique-north`.** `oblique-n` is not a valid product type and Vexcel silently
  returned a top-down image; fixed in c3fedf3 and the Houston cache re-fetched.
- **SQLite run history via SQLModel** (`DATABASE_URL`, default `sqlite:///./turnkey.db` resolved
  relative to `backend/`). Every `/analyze` response is stored verbatim, which gives shareable,
  reloadable `/analysis/{id}` URLs. There are no migrations; the DB is disposable (delete it to reset).
  Stored runs re-validate on read, so new fields get defaults.

### Agents and rules
- **Requirements parser:** the regex parser is always available. If `ANTHROPIC_API_KEY` is set, Claude
  (`ANTHROPIC_MODEL`, default `claude-haiku-5-5`) is tried first with schema-constrained JSON, an 8 s
  timeout and no retries; any error falls back to regex. This is the only LLM in our code (image
  analysis is Vexcel's AI, consumed as facts).
- **Deterministic cost bands, no ML, ranges only** (`costs.yaml`). Permits are always included.
  Soft costs are listed in `line_items` / `breakdown`, so they sum to `fit_out_estimate`.
- **Ranking with a minimum fit score of 55** (was 25): qualifying spaces (score >= `ranking.min_score`)
  by first-year cost, then **weak fit** spaces, then disqualified spaces; ties by score. 55 means
  "clearly more than half of the weighted, scored criteria pass". At 25, the Houston medical office
  (3701 Kirby, exactly 50 for a restaurant) out-ranked real restaurant candidates because its large TI
  made it look cheap. Config-driven; 0 disables the gate.
- **Criteria registry in YAML, hot-reloaded.** Adding or re-weighting a criterion is a config edit.
  New logic is one decorated evaluator function. The UI never hard-codes criterion ids.
- **Hard block only on a definitive failure.** Missing data never disqualifies.
- **Jurisdiction rules are config-driven.** `zoning_mode: districts | none`, `use_restriction_blocks`,
  `parking_ratios`, `parking_exempt_areas` and the plumbing code live in `jurisdictions.yaml`; adding a
  city is a YAML block.
- **Evaluator specifics:**
  - **Houston zoning:** no zoning ordinance → PASS with a "verify deed restrictions" note and landlord
    question. A **disclosed use restriction** that prohibits the use (e.g. `no_food_service`) is a
    definitive failure in any city: deed restrictions can't be permitted around (Houston enforces them,
    Code Ch. 10 §§10-551–555).
  - **Parking requirement per property:** the city minimum for the listing's actual size and location
    (Houston §26-492 ratios; 0 in the Downtown / EaDo market-based areas, §26-471), never below a
    user-stated number; with no city minimum, the user's number or the business guideline. When the user
    gives no number in a city with minimums, `parking_source` is `"jurisdiction"`.
  - **Parking estimate from Vexcel paved area only when it is at least one space** (350 sq ft/space).
    Urban parcels report a few sq ft of paving because parking is shared or on the street; emitting
    "0 spaces" would be a false negative. `vehicles_count` is context only.
  - **HVAC prorated to the suite share** (`prorate_by_footprint`): Vexcel counts rooftop units for the
    whole building, so capacity = building tons × suite sq ft ÷ footprint sq ft. A **short prorated share
    is UNKNOWN "verify with landlord"**: excluded from the score, no cost, landlord question. The share is
    an estimate and the building's units may serve the suite; penalizing it pushed good restaurant
    spaces (1903 Yale) down on a guess. Zero detected units, or short direct (fixture) tonnage, stay RISK
    with an `hvac_rtu` cost.
  - **Roof condition** (new criterion, weight 5): Vexcel AI score >= 3 and no tarp / structural damage →
    PASS; otherwise RISK with a `roof_repair` line priced per sq ft of the **suite** (a tenant's share,
    not the whole roof). Never a hard block. No data (Austin) → UNKNOWN, not scored.
  - `window_visibility` is restaurant-only. Below the threshold it is **RISK** (scored 0), where the
    scale-criteria prompt suggested UNKNOWN. With no window data it is ignored.
  - Missing sprinklers where IBC §903.2 requires them are **priced as a retrofit, not disqualifying**.
    `fire_safety` has weight 0 and never reports a definitive failure, so **`zoning_use` is the only
    practical hard block** (zoning district or use restriction).
  - HVAC need = **max**(seat/space-need based tons from the parser, the listing's floor area ÷ sq ft per ton).

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Vexcel geofence**: the key works only in Los Angeles and Houston (403 elsewhere) | Demo in Houston; other cities fall back to placeholders per item with the 403 remembered; Austin kept as an offline dataset |
| **Key expiry** (2026-12-01) or revocation | Pre-warmed cache serves the demo with no calls; mock mode replays snapshot facts with identical ranking |
| **Sample listings** mistaken for market data | "Sample listing" badge + tooltip; `listing_source` on every result; stated in the demo script; real CoStar listings replace them via `map_costar_listing` |
| **Building-level Vexcel data** (rooftop units, footprint, roof) applied to a suite | HVAC prorated by floor area with a "verify" result instead of a penalty; footprint labelled "whole building"; roof repair priced on the suite's sq ft; notes say "whole building" |
| **Parcel-level paving** (shared lots, street parking not included) | No estimate below one space; parking UNKNOWN with a landlord question rather than "0 spaces"; estimate confidence 0.4 and labelled "not a striped-space count" |
| Houston rules simplified (conservative parking areas, full restaurant ratio, deed restrictions only when disclosed) | Citations on every result, conservative choices documented in `jurisdictions.yaml`, a deed-restriction landlord question on every Houston result, disclaimer |
| CoStar / Matterport APIs unavailable or endpoints unknown | Mock fixtures; tolerant mapping and fixture fallback ready |
| Cost estimates taken as quotes | Ranges only, assumptions listed, disclaimer on every report and in the letter |
| Interior facts are mocked | Facts carry confidence; < 0.7 is flagged "verify on site"; overlays are illustrative |
| Licensed imagery leaks | Cache gitignored; only derived facts are snapshotted; attribution shown under live imagery |
| Vexcel key leaks | Header-only, backend-only, redacted from logs (tested); rotate any key that was pasted anywhere |
| Claude returns bad output or is slow | Strict schema, range checks, 8 s timeout, regex fallback; tests use a fake client |
| Broken YAML during a live edit | Validation error names the entry; malformed registry → clear 500; unknown evaluator → UNKNOWN |
| Live demo failure | Warm cache, mock mode with identical numbers, Austin dataset, Playwright E2E, pre-opened report tab, curl fallback ([DEMO_RUNBOOK.md](DEMO_RUNBOOK.md)) |
| Stored analyses readable by anyone with the id | Acceptable for a local demo; add auth before deployment |

## Known issues

Found while writing the docs (not fixed; code owners to decide).

1. **Hand-made parking boxes drawn on live imagery** (open). The box rule drops live/snapshot boxes over
   the placeholder SVG, but not the reverse: in live mode, the Houston fixtures' hand-made
   `visible_parking_count` boxes (drawn for the 4:3 placeholder SVG) are drawn over the real 800×800
   ortho, where they don't line up (hou-01, -02, -03, -04). Fix idea: drop non-snapshot fixture boxes
   when `aerial_source == "vexcel-live"`.
2. **Grease interceptor citation is Austin-specific** (open). `criteria.yaml` `grease_interceptor.source`
   cites the "Austin Water pretreatment program" for all cities, including Houston, whose `grease_code`
   (Code Ch. 47, Art. XI) is recorded in `jurisdictions.yaml` but not read.
3. **Unused config** (open). `GEOCODING_API_KEY` and the `jurisdictions.yaml` keys `building_code`,
   `health_code`, `grease_code` and `plumbing_fixture_note` are loaded but not read by any code.
4. **Stale code comment** (open). `business_types.yaml` says `parking_per_capacity_unit` is "used only
   when the user doesn't state a parking number"; it is now also skipped when the city sets a minimum.
5. **`/health` vs `mode.parser`** (intended). `/health` reports the *configured* parser, while
   `AnalyzeResponse.mode.parser` reports the parser *actually used*. Documented in API_CONTRACT.md.

Fixed since the last docs pass: the zoning fallback citation is now generic ("Local zoning / land-use
rules for the property's city"), with the city citation from `jurisdictions.yaml`; the dental fallback
unit in `BusinessProfileForm.tsx` says "chairs"; the State input is `required` with `minLength={2}`.
