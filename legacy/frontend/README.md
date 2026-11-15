# Turnkey Matchmaker frontend

Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS v4. See the repo [README](../README.md)
and [docs/FRONTEND_DESIGN.md](../docs/FRONTEND_DESIGN.md) for the full picture.

## Run

```bash
npm install
npm run dev        # http://localhost:3000 (start the backend on :8000 first)
```

Browser code calls relative URLs. `next.config.ts` rewrites `/api/v1/*`, `/static/*` and `/health`
to `API_ORIGIN` (default `http://localhost:8000`). To use another backend, set it in `.env.local`:

```bash
API_ORIGIN=http://localhost:8000
```

`API_ORIGIN` is read server-side by `next.config.ts`, so it needs no `NEXT_PUBLIC_` prefix.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Dev server (Turbopack) |
| `npm run build` / `npm start` | Production build / serve |
| `npm test` | Vitest + React Testing Library (`test/**/*.test.ts(x)`, jsdom); 64 tests in 8 files |
| `npm run lint` | ESLint (`eslint-config-next`) |
| `npm run e2e` | Playwright end-to-end: Austin and Houston demo flows + error state, desktop and 375px mobile (starts the backend in mock mode and the frontend, or reuses servers already running) |

## Layout

- `app/`: `/` (profile form + recent analyses), `/properties` (candidate spaces with Sample listing /
  use-restriction badges + criteria),
  `/analysis/[id]` (stored report)
- `components/`: page components, `analysis/*` report sections, `ui/*` primitives (Button, Card, Badge, ...)
- `lib/`: `api.ts` (typed client), `types.ts` (mirror of `docs/API_CONTRACT.md`), `format.ts`,
  `overlay.ts` (evidence boxes, building footprint), `useAsync.ts`
- Media: images (placeholder SVGs, cached live Vexcel JPEGs) come from the backend's `/static` via the
  rewrite and render as plain `<img>`. The aerial (`components/analysis/AerialPanel.tsx`) uses a square
  frame, a "Live · Vexcel" badge + attribution for live imagery, and Top-down / Angled tabs. The browser
  never calls Vexcel or sees its key.
- AI (backend LLM, local Ollama `qwen3:8b` by default): `components/analysis/AiSummaryPanel.tsx` shows the
  grounded `ai_summary` with a "Local AI · qwen3:8b" badge and the caveat that costs and compliance are
  rule-based; the comparison table adds a "Why (AI)" row and each card a one-line reason; the report shows
  parser / LLM badges; the header pill adds "Local AI ready" and the progress overlay a "Writing summary
  (local AI)" step when `/health` reports an Ollama model. All of it disappears when there is no summary.
- The profile form defaults to Houston, TX (the demo city).
- Theme tokens (navy surfaces, cyan accent, PASS/RISK/UNKNOWN colors) live in `app/globals.css` under
  `@theme`. There is no `tailwind.config.js`.
