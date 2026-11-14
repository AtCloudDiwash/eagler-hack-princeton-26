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
- **FastAPI + Pydantic v2** with a synchronous pipeline. The deterministic part of a 5-property analysis
  runs in milliseconds (mock or warm Vexcel cache); with the warm local LLM the whole request takes about
  7 s, still short enough for a spinner, so there are no background jobs or polling.
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
- **Local LLM for parsing and explanations only** (`LLM_PROVIDER=ollama`, `qwen3:8b`). The LLM does two
  things: (1) extract requirement fields from the free text, merged over the always-on regex parser, and
  (2) write one grounded `ai_summary` of the **already computed** ranking. It never computes costs,
  scores, compliance statuses or ranks (CLAUDE.md: deterministic, rule-based cost engine; no ML for
  costs). Why local: free, no key, works offline at the venue, and the owner's plans and budget never
  leave the machine. Why qwen3:8b: reliable JSON with Ollama's schema-constrained `format`, fast enough
  on a laptop (parse 1.4-1.7 s, summary 5.6-6.1 s warm on an M4 Pro); `qwen3:14b` reads slightly better
  but is about 2x slower. Calls use `think: false` (qwen3's reasoning trace would add seconds) and
  `temperature: 0`.
- **Fail closed to deterministic.** Ollama down, model not pulled, timeout (`LLM_TIMEOUT_SECONDS`, 20 s),
  truncated or invalid JSON → regex parser and `ai_summary: null`; the UI then simply hides the panel.
  Availability is probed with `GET /api/tags` and cached 30 s, so a missing Ollama costs nothing per
  request.
- **Grounding guardrail instead of trusting the summary.** The LLM only sees a compact digest of the
  result (preformatted `$` strings, scores, statuses, top flags). Its output is rejected if any `$` figure,
  quoted fit score or property id is not in the digest. Rejecting the whole summary is simpler and safer
  than editing it.
- **Claude is a provider option, not the default.** `LLM_PROVIDER=anthropic` (+ `ANTHROPIC_API_KEY`) routes
  the same two calls to Claude. A key alone no longer switches the parser to Claude, so a stray key in
  `.env` can't silently send data to a cloud API. Image analysis remains Vexcel's AI, consumed as facts.
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
| LLM returns bad output (Ollama or Claude) | Schema-constrained JSON, range checks on parsed fields, `<think>` stripping, truncation detection; regex fallback / `ai_summary: null`; tests use a fake Ollama server and a fake Claude client |
| **Wrong non-numeric claims slip through the guardrail** (e.g. calling a PASS a risk, a wrong reason for a rank) | The guardrail checks only `$` figures, scores and ids. Mitigated by the digest containing statuses and reasons verbatim, a prompt that forbids contradicting statuses, `temperature: 0`, the caveat "Written by AI from the numbers below; costs and compliance are rule-based", and the deterministic results shown right below it. Read the summary during the dry run |
| **LLM latency** (warm ~7 s per analysis, ~14 s cold, 14b ~13 s) | Background warm-up at startup, `keep_alive` 30 min, a fixed `num_ctx` (no reloads), one summary call per analysis (not per property), a "Writing summary (local AI)" progress step; `LLM_PROVIDER=none` for millisecond runs |
| **Memory** (5.2 GB model resident; 8b + 14b together thrash) | Default to 8b, run one model at a time, close heavy apps before the demo; Ollama unloads after `OLLAMA_KEEP_ALIVE` |
| Ollama not running on the demo machine | Same ranking via regex, panel hidden; `/health` and the "Local AI ready" pill show the state before the demo |
| Broken YAML during a live edit | Validation error names the entry; malformed registry → clear 500; unknown evaluator → UNKNOWN |
| Live demo failure | Warm cache, mock mode with identical numbers, Austin dataset, Playwright E2E, pre-opened report tab, curl fallback ([DEMO_RUNBOOK.md](DEMO_RUNBOOK.md)) |
| Stored analyses readable by anyone with the id | Acceptable for a local demo; add auth before deployment |

## Known issues

Found while writing the docs.

1. **Unused config** (open). `GEOCODING_API_KEY` and the `jurisdictions.yaml` keys `building_code`,
   `health_code` and `plumbing_fixture_note` are loaded but not read by any code (`grease_code` is now
   read by the grease interceptor check).
2. **`/health` vs `mode.parser`** (intended). `/health` reports the parser / LLM that is *configured and
   reachable right now* (Ollama probe cached 30 s), while `AnalyzeResponse.mode.parser` / `mode.llm`
   report what was *actually used* in that run. Documented in API_CONTRACT.md.
3. **Summary step depends on `/health`** (cosmetic). The frontend adds the "Writing summary" progress step
   from `/health` `mode.llm`, fetched when `/properties` loads; if Ollama stops in between, the step still
   shows and the report simply has no panel.

Fixed after the Houston docs pass: overlay boxes now follow the image they were drawn for (hand-made
fixture boxes are dropped over live Vexcel imagery, snapshot/live boxes over the placeholder SVG); the
grease interceptor check cites the city's own `grease_code` (Houston Code Ch. 47, Art. XI; Austin Water
pretreatment program) and the criterion source is generic; the `business_types.yaml` parking comment
mentions city minimums.

Fixed since the last docs pass: the zoning fallback citation is now generic ("Local zoning / land-use
rules for the property's city"), with the city citation from `jurisdictions.yaml`; the dental fallback
unit in `BusinessProfileForm.tsx` says "chairs"; the State input is `required` with `minLength={2}`.
