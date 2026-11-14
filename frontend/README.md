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
| `npm test` | Vitest + React Testing Library (`test/**/*.test.ts(x)`, jsdom) |
| `npm run lint` | ESLint (`eslint-config-next`) |
| `npm run e2e` | Playwright end-to-end demo flow (starts backend and frontend) |

## Layout

- `app/`: `/` (profile form + recent analyses), `/properties` (candidate spaces + criteria),
  `/analysis/[id]` (stored report)
- `components/`: page components, `analysis/*` report sections, `ui/*` primitives (Button, Card, Badge, ...)
- `lib/`: `api.ts` (typed client), `types.ts` (mirror of `docs/API_CONTRACT.md`), `format.ts`,
  `overlay.ts`, `useAsync.ts`
- Theme tokens (navy surfaces, cyan accent, PASS/RISK/UNKNOWN colors) live in `app/globals.css` under
  `@theme`. There is no `tailwind.config.js`.
