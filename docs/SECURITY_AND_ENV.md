# Security and Environment

## Setup

```bash
cd backend && cp ../.env.example .env        # backend reads backend/.env (python-dotenv)
# optional, frontend only:
echo "API_ORIGIN=http://localhost:8000" > frontend/.env.local
```

The `.env.example` placeholders (values starting with `your_`) are treated as "not set", so the
copied file runs everything in mock mode. Env vars are read once at startup; restart uvicorn or
`npm run dev` after changing them. YAML config changes (criteria, costs) need no restart.

## Variables

Verified against `backend/app/config.py` (`os.getenv`) and `frontend/next.config.ts`
(`process.env`). No other env vars are read.

| Name | Used by | Default | Required? | Purpose |
|---|---|---|---|---|
| `USE_MOCK_DATA` | backend `config.py` | `true` | no | `true`/`1`/`yes`/`on` = always use fixtures. `false` lets keyed providers go live |
| `PROVIDER_TIMEOUT_SECONDS` | backend providers | `8` | no | Timeout per live HTTP call |
| `COSTAR_API_KEY` | `costar_provider` | unset | only for live CoStar | Bearer token |
| `COSTAR_API_BASE_URL` | `costar_provider` | `https://api.costar.example/v1` (placeholder) | for live CoStar | Base URL; `/listings` is appended |
| `MATTERPORT_API_KEY` | `matterport_provider` | unset | only for live Matterport | Basic-auth credential |
| `MATTERPORT_API_BASE_URL` | `matterport_provider` | `https://api.matterport.com/api/models/graph` | no | GraphQL endpoint |
| `VEXCEL_API_KEY` | `vexcel_provider` | unset | only for live Vexcel | Bearer token |
| `VEXCEL_API_BASE_URL` | `vexcel_provider` | `https://api.vexcel.example/v1` (placeholder) | for live Vexcel | Base URL; `/images/ortho` is appended |
| `GEOCODING_API_KEY` | `config.py` only | unset | no | Reserved; read but not used yet |
| `ANTHROPIC_API_KEY` | `requirements_parser` | unset | no | Enables the Claude parser (regex fallback always on) |
| `ANTHROPIC_MODEL` | `requirements_parser` | `claude-haiku-5-5` | no | Claude model id |
| `CRITERIA_PATH` | `criteria_manager` | `backend/criteria.yaml` | no | Alternate criteria registry |
| `CORS_ORIGINS` | `main.py` | `http://localhost:3000` | no | Comma-separated allowed origins |
| `DATABASE_URL` | `db.py` | `sqlite:///./turnkey.db` (relative to `backend/`) | no | Run-history database |
| `API_ORIGIN` | frontend `next.config.ts` (server-side) | `http://localhost:8000` | no | Where the Next.js dev server proxies `/api/v1`, `/static`, `/health` |

**No `NEXT_PUBLIC_` variables exist.** The browser only calls relative URLs, and `API_ORIGIN` is
read at build/dev-server time by `next.config.ts`, so it is never exposed to client code. Never put
a secret in a `NEXT_PUBLIC_` variable.

## Git hygiene

`.gitignore` excludes `backend/.env`, `backend/.env.local`, `frontend/.env.local`, `backend/venv/`,
`frontend/node_modules/`, `frontend/.next/`, `backend/*.db` (including `turnkey.db`) and caches.
Only `.env.example` (placeholders) is committed. The test suite pins `DATABASE_URL` to a temp file
and blanks every API key (`tests/conftest.py`), so tests never touch the network or your real DB.

## Practices in the code

- Keys are never logged; startup logs show only modes (`mock`/`live`, `regex`/`claude`) and the DB URL.
- Live calls use HTTPS base URLs, explicit timeouts, and no retries for Claude. Every failure falls back.
- CORS allows only `CORS_ORIGINS`. In normal use the frontend goes through the same-origin Next.js
  proxy, so CORS matters only for direct API calls.
- Input is validated by Pydantic (422) and property / business type ids are checked (404 / 400).
  SQL goes through SQLModel (parameterized).
- The drafted landlord letter is plain text rendered by React (escaped), not HTML.

## Out of scope for the hackathon

Authentication and authorization (anyone who can reach the API can read stored analyses by id),
rate limiting, and HTTPS termination. Add these before any public deployment (e.g. AWS behind
an ALB/API Gateway).
