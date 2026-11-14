# Frontend Design

Next.js 16 **App Router** (`frontend/app/`), React 19, TypeScript, Tailwind CSS v4 and Heroicons.
UI components are hand-rolled in `components/ui/` (no shadcn). All data comes from the REST API
through `lib/api.ts` using relative URLs, which `next.config.ts` rewrites to `API_ORIGIN`.

## Routes

| Route | Files | What it does |
|---|---|---|
| `/` | `app/page.tsx` | Hero + three highlights, `BusinessProfileForm`, `RecentAnalyses` (last 10 stored runs) |
| `/properties?type=&details=&city=&state=` | `app/properties/page.tsx` → `PropertiesView.tsx` | Loads `GET /properties` and `GET /criteria` for the profile. Shows a property card grid with Select all / Clear, a collapsible "Criteria used" table, and a sticky "Compare N selected" bar. On compare it `POST /analyze`s with the `AnalyzeProgress` overlay, then navigates to the report |
| `/analysis/[id]` | `app/analysis/[id]/page.tsx` → `AnalysisView.tsx` | Loads `GET /analyses/{id}`. Shows `RequirementsSummary`, `ComparisonTable`, one `AnalysisCard` per property in rank order, and the disclaimer. A 404 gets a "not found" empty state. The URL is shareable |

Pages are server components that wrap a client view in `<Suspense>`, because the views read
`useSearchParams` / `useParams` (`cacheComponents: true` in `next.config.ts`). The profile form
passes its state through the query string, so `/properties?...` URLs are shareable too.

## Components

| Component | Purpose |
|---|---|
| `SiteHeader` / `SiteFooter` | Sticky header with logo and `ApiStatus`, plus the footer |
| `ApiStatus` | `GET /health` pill: "API · mock data" / "mixed data" / "live data" / "API offline" |
| `BusinessProfileForm` | Business type select (from `/business-types`, with an offline fallback list), details input with a **Use example** button (example built from the type's config), city/ZIP, state |
| `RecentAnalyses` | Links to stored runs; hidden when empty or when the API is down |
| `PropertyCard` | Photo, address, size, rent, zoning, TI/sq ft, previous use; the whole card toggles selection |
| `CriteriaTable` | Renders any list of criteria: description, domain, weight, hard block and source columns, with required inputs, missing-data policy and jurisdictions under each description. No criterion ids are hard-coded |
| `AnalyzeProgress` | Modal with cosmetic steps (parsing, listings, compliance, fit-out) while `/analyze` runs |
| `MediaImage` | Image with loading/error placeholder; `fit="natural"` keeps the aspect ratio for overlays |
| `analysis/RequirementsSummary` | Parsed requirements chips, assumptions, ranking basis, provider and parser mode badges |
| `analysis/ComparisonTable` | One column per property: rank (+ weak-fit badge), score, cost to open, first-year cost, rent, build-out, TI, status |
| `analysis/WeakFitBadge` | "Weak fit" badge for results with `weak_fit: true` (score below `min_score`) |
| `analysis/AnalysisCard` | Full report for one property: `ScoreRing`, rank / disqualified badges, six key numbers, `CostBreakdown`, `MediaPanel`, `CriteriaResults`, landlord questions, `LandlordLetter`, observations, assumptions |
| `analysis/CostBreakdown` | Line items with reasons, any extra breakdown entries, and the roll-up to cost to open |
| `analysis/CriteriaResults` | PASS/RISK/UNKNOWN counts; results grouped by domain (`groupByDomain`), each with a status badge, notes, an `InfoTip` source citation and evidence chips |
| `analysis/MediaPanel` + `ImageOverlay` | Aerial (Vexcel) and floor plan (Matterport) with numbered evidence boxes plus a legend; Matterport iframe when `matterport_embed_url` exists. See [VISION_OVERLAYS.md](VISION_OVERLAYS.md) |
| `analysis/LandlordLetter` | Drafted letter with a copy-to-clipboard button |
| `analysis/ScoreRing` | 0-100 ring: green >= 75, cyan >= 50, orange below (or when disqualified) |
| `ui/*` | `Button` / `ButtonLink` (primary, secondary, ghost), `Card`, `SectionTitle`, `Badge` / `StatusBadge`, `EmptyState` / `ErrorState`, `InfoTip`, `Spinner` / `LoadingBlock` |

## Data layer

- `lib/api.ts`: `api.health`, `businessTypes`, `criteria`, `properties`, `analyze`, `analyses`,
  `analysis`. Throws `ApiError(status, message)` using FastAPI's `detail` (status 0 = network
  failure, with a "Is the backend running on port 8000?" hint). `toQuery` skips empty params.
- `lib/useAsync.ts`: keyed loading / error / success state with abort on change and `retry()`.
- `lib/types.ts`: TypeScript mirror of [API_CONTRACT.md](API_CONTRACT.md).
- `lib/format.ts`: currency, compact currency, ranges ("$84k – $132k"), months, sq ft, percent,
  `humanize`, `formatValue`. Missing values render as "N/A".
- `lib/overlay.ts`: `boxToStyle`, `overlayEvidence`.

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
- Every fetch has loading, error (with retry) and empty states. The form still works when the API is
  down because it falls back to the built-in business types.
- Accessibility: labeled inputs, the card checkbox is a real (visually hidden) input,
  `role="status"` spinners, `role="alert"` for disqualification, and a keyboard-focusable `InfoTip`.

## Not built

A settings page for editing weights (weights are edited in `criteria.yaml`), maps, and auth.
