# Frontend Design

Next.js 16 **App Router** (`frontend/app/`), React 19, TypeScript, Tailwind CSS v4 and Heroicons.
UI components are hand-rolled in `components/ui/` (no shadcn). All data comes from the REST API
through `lib/api.ts` using relative URLs, which `next.config.ts` rewrites to `API_ORIGIN`.

## Routes

| Route | Files | What it does |
|---|---|---|
| `/` | `app/page.tsx` | Hero + three highlights, `BusinessProfileForm`, `RecentAnalyses` (last 10 stored runs) |
| `/properties?type=&details=&city=&state=` | `app/properties/page.tsx` → `PropertiesView.tsx` | Loads `GET /properties` and `GET /criteria` for the profile. Shows a property card grid with Select all / Clear, a collapsible "Criteria used" table, and a sticky "Compare N selected" bar. It also reads `GET /health` to decide whether the progress overlay gets a "Writing summary" step (steps advance every 1.0 s with an LLM, 1.4 s without). On compare it `POST /analyze`s with the `AnalyzeProgress` overlay, then navigates to the report |
| `/analysis/[id]` | `app/analysis/[id]/page.tsx` → `AnalysisView.tsx` | Loads `GET /analyses/{id}`. Shows `RequirementsSummary`, `AiSummaryPanel` (when the run has an `ai_summary`), `ComparisonTable`, one `AnalysisCard` per property in rank order, and the disclaimer. A 404 gets a "not found" empty state. The URL is shareable |

Pages are server components that wrap a client view in `<Suspense>`, because the views read
`useSearchParams` / `useParams` (`cacheComponents: true` in `next.config.ts`). The profile form
passes its state through the query string, so `/properties?...` URLs are shareable too.

## Components

| Component | Purpose |
|---|---|
| `SiteHeader` / `SiteFooter` | Sticky header with logo and `ApiStatus`, plus the footer |
| `ApiStatus` | `GET /health` pill: "API · mock data" / "mixed data" / "live data" / "API offline" (decided by the data providers only; `parser` / `llm` are ignored), plus "· Local AI ready" (md+ screens) when `mode.llm` is an `ollama:` model |
| `BusinessProfileForm` | Business type select (from `/business-types`, with an offline fallback list), details input with a **Use example** button (example built from the type's config), city/ZIP (default **Houston**), state (default TX, required, 2 letters) |
| `RecentAnalyses` | Links to stored runs; hidden when empty or when the API is down |
| `PropertyCard` | Photo, address, size, rent, zoning, TI/sq ft, previous use; a **Sample listing** badge with tooltip when `listing_source === "sample"`; an orange **Use restriction: ...** line when `use_restrictions` is non-empty; the whole card toggles selection |
| `CriteriaTable` | Renders any list of criteria: description, domain, weight, hard block and source columns, with required inputs, missing-data policy and jurisdictions under each description. No criterion ids are hard-coded |
| `AnalyzeProgress` | Modal with cosmetic steps (parsing, listings, compliance, fit-out) while `/analyze` runs; `analysisSteps(llm)` appends "Writing summary (local AI)" (Ollama) or "Writing summary (AI)" (other LLM) when `/health` reports one |
| `MediaImage` | Plain `<img>` with an error placeholder; `fit="cover"`, `"contain"` (letterbox in a fixed frame, used for the angled photo) or `"natural"` (own aspect, needed for overlays) |
| `analysis/RequirementsSummary` | Parsed requirements chips (parking labelled "you said" / "city code" / "guideline"), assumptions, ranking basis; mode badges: providers (mock/live), then "parser: Regex / Ollama / Claude" (accent unless regex) and the summary model ("Local AI · qwen3:8b") when `mode.llm` isn't `none` |
| `analysis/AiSummaryPanel` | "AI summary" section (sparkles icon, accent border) with the summary text, a model badge ("Local AI · qwen3:8b" / "Claude · ..."), and the caveat "Written by AI from the numbers below; costs and compliance are rule-based." Renders nothing for a `null` / missing / blank summary (no LLM, rejected, or an older run). `aiSentenceFor(summary, id)` returns the per-property sentence |
| `analysis/ComparisonTable` | One column per property: rank (+ weak-fit badge), score, cost to open, first-year cost, rent, build-out, TI, status; a final **Why (AI)** row when the summary covers at least one property |
| `analysis/WeakFitBadge` | "Weak fit" badge for results with `weak_fit: true` (score below `min_score`) |
| `analysis/AnalysisCard` | Full report for one property: `ScoreRing`, rank / disqualified badges, the AI's one-line "why this rank" under the address (when present), six key numbers, `CostBreakdown`, `MediaPanel`, `CriteriaResults`, landlord questions, `LandlordLetter`, observations, assumptions |
| `analysis/CostBreakdown` | Line items with reasons, any extra breakdown entries, and the roll-up to cost to open |
| `analysis/CriteriaResults` | PASS/RISK/UNKNOWN counts; results grouped by domain (`groupByDomain`), each with a status badge, notes, an `InfoTip` source citation and evidence chips (with a live dot for live evidence) |
| `analysis/MediaPanel` | `AerialPanel` + floor plan (Matterport, `ImageOverlay`) side by side; Matterport 3D tour iframe when `matterport_embed_url` exists, else a "No Matterport 3D tour" note |
| `analysis/AerialPanel` | Vexcel aerial in a **square frame**: "Live · Vexcel" badge + attribution for live imagery, else "Placeholder imagery"; **Top-down / Angled** tabs when `oblique_url` exists; evidence boxes and the dashed building footprint on the top-down view; legend. See [VISION_OVERLAYS.md](VISION_OVERLAYS.md) |
| `analysis/ImageOverlay` | `OverlayImage` (image + normalized boxes, `frame="natural" \| "square"`), `EvidenceLegend`, captioned `ImageOverlay` |
| `analysis/LandlordLetter` | Drafted letter with a copy-to-clipboard button |
| `analysis/ScoreRing` | 0-100 ring: green >= 75, cyan >= 50, orange below (or when disqualified) |
| `ui/*` | `Button` / `ButtonLink` (primary, secondary, ghost), `Card`, `SectionTitle`, `Badge` / `StatusBadge`, `EmptyState` / `ErrorState`, `InfoTip` (named `group/tip`, optional `align="start"`), `LiveDot` (cyan "live" marker for `evidence.live`), `Spinner` / `LoadingBlock` |

## Data layer

- `lib/api.ts`: `api.health`, `businessTypes`, `criteria`, `properties`, `analyze`, `analyses`,
  `analysis`. Throws `ApiError(status, message)` using FastAPI's `detail` (status 0 = network
  failure, with a "Is the backend running on port 8000?" hint). `toQuery` skips empty params.
- `lib/useAsync.ts`: keyed loading / error / success state with abort on change and `retry()`.
- `lib/types.ts`: TypeScript mirror of [API_CONTRACT.md](API_CONTRACT.md), including `AiSummary` and
  `mode.parser` / `mode.llm`.
- `lib/format.ts`: currency, compact currency, ranges ("$84k – $132k"), months, sq ft, percent,
  `humanize`, `formatValue`, `parkingSourceLabel`, and the AI helpers `parserLabel`, `hasLlm`,
  `isLocalLlm`, `llmLabel` ("ollama:qwen3:8b" → "Local AI · qwen3:8b"). Missing values render as "N/A".
- `lib/overlay.ts`: `boxToStyle`, `overlayEvidence`, `isFootprint`.

## Theme (`app/globals.css`)

Tailwind v4 reads tokens from `@theme`; there is no `tailwind.config.js`. Use them as utilities
(`bg-navy-950`, `bg-surface`, `text-accent`, `border-line`, `text-pass`, ...).

| Token | Value | Use |
|---|---|---|
| `--color-navy-950` | `#0b1220` | Page background |
| `--color-navy-900` | `#0f172a` | Inputs, image wells, sticky bar |
| `--color-surface` / `--color-surface-raised` | `#131c2e` / `#1a2540` | Cards / secondary buttons |
| `--color-line` | `#26324d` | Borders, dividers |
| `--color-ink` / `--color-ink-muted` | `#e6edf7` / `#94a3b8` | Text |
| `--color-accent` / `--color-accent-strong` | `#22d3ee` / `#06b6d4` | Teal/cyan accent, primary button, overlays |
| `--color-pass` / `--color-risk` / `--color-unknown` | `#34d399` / `#fb923c` / `#94a3b8` | Status badges |

Fonts: Geist Sans / Geist Mono via `next/font`. Disqualification uses Tailwind's red palette.

## Responsive and states

- Mobile-first grids: property cards use 1 / 2 / 3 columns; key numbers use 2 / 3 / 6 columns. The
  comparison table scrolls horizontally on small screens. The Playwright E2E runs the demo at 375px.
- AI content is always optional: every AI element (panel, Why row, card sentence, badges, pill, progress
  step) is hidden when the backend has no LLM or the summary was rejected, and older stored runs without
  `ai_summary` / `mode.llm` render unchanged.
- Every fetch has loading, error (with retry) and empty states. The form still works when the API is
  down because it falls back to the built-in business types.
- Accessibility: labeled inputs, the card checkbox is a real (visually hidden) input,
  `role="status"` spinners, `role="alert"` for disqualification, and a keyboard-focusable `InfoTip`.

## Media

Images are plain `<img>` elements, never the Next.js optimizer: they are placeholder SVGs or cached
Vexcel JPEGs served by the backend at `/static/...` (proxied by `next.config.ts`). The aerial frame is
square because live orthos are 800 × 800; the 4:3 placeholder SVGs letterbox inside it.

## Not built

A settings page for editing weights (weights are edited in `criteria.yaml`), maps, and auth.
