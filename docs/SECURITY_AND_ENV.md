# Security and Environment

## Setup

```bash
cd backend && cp ../.env.example .env        # backend reads backend/.env (python-dotenv)
# optional, frontend only:
echo "API_ORIGIN=http://localhost:8000" > frontend/.env.local
```

The `.env.example` placeholders (values starting with `your_`) are treated as "not set", so the
copied file runs everything in mock mode. For live Vexcel imagery set `USE_MOCK_DATA=false` and
`VEXCEL_API_KEY` in `backend/.env` ([DEMO_RUNBOOK.md](DEMO_RUNBOOK.md)). The local LLM needs no env
vars at all: the defaults (`LLM_PROVIDER=ollama`, `OLLAMA_MODEL=qwen3:8b`) work once
`ollama pull qwen3:8b` has run and Ollama is serving ([INTEGRATIONS.md](INTEGRATIONS.md#ollama)). Env vars are read once at
startup; restart uvicorn or `npm run dev` after changing them. YAML config changes (criteria, costs,
jurisdictions) need no restart.

## Variables

Verified against `backend/app/config.py` (`os.getenv`) and `frontend/next.config.ts`
(`process.env`). No other env vars are read (the test suite and Playwright config set some of these
for their own runs).

| Name | Used by | Default | Required? | Purpose |
|---|---|---|---|---|
| `USE_MOCK_DATA` | backend `config.py` | `true` | no | `true`/`1`/`yes`/`on` = always use fixtures. `false` lets keyed providers go live |
| `PROVIDER_TIMEOUT_SECONDS` | backend providers | `8` | no | Timeout per live HTTP call |
| `COSTAR_API_KEY` | `costar_provider` | unset | only for live CoStar | Bearer token |
| `COSTAR_API_BASE_URL` | `costar_provider` | `https://api.costar.example/v1` (placeholder) | for live CoStar | Base URL; `/listings` is appended |
| `MATTERPORT_API_KEY` | `matterport_provider` | unset | only for live Matterport | Basic-auth credential |
| `MATTERPORT_API_BASE_URL` | `matterport_provider` | `https://api.matterport.com/api/models/graph` | no | GraphQL endpoint |
| `VEXCEL_API_KEY` | `vexcel_provider` | unset | for live Vexcel | Sent only as the `X-API-KEY` header. The sponsor key is geofenced to Los Angeles + Houston and expires 2026-12-01 |
| `VEXCEL_API_BASE_URL` | `vexcel_provider` | `https://api.vexcelgroup.com/v2` | no | `/ortho/extract`, `/oriented/extract`, `/property/extract` are appended |
| `GEOCODING_API_KEY` | `config.py` only | unset | no | Reserved; read but not used yet |
| `LLM_PROVIDER` | `llm.py` | `ollama` | no | `ollama` (local) \| `anthropic` (Claude) \| `none`. Picks the LLM for requirements parsing and the `ai_summary`; any other value = `none` |
| `OLLAMA_BASE_URL` | `llm.py` | `http://localhost:11434` | no | Ollama server (`/api/tags`, `/api/chat`, `/api/generate`) |
| `OLLAMA_MODEL` | `llm.py` | `qwen3:8b` | no | Ollama model; must be pulled. `qwen3:14b` works, about 2x slower |
| `OLLAMA_KEEP_ALIVE` | `llm.py` | `30m` | no | How long Ollama keeps the model loaded after a call (`-1` = forever) |
| `OLLAMA_NUM_CTX` | `llm.py` | `8192` | no | Context window in tokens (the 4-5 property digest is ~1.5k tokens) |
| `LLM_TIMEOUT_SECONDS` | `llm.py` | `20` | no | Timeout per LLM call (Ollama or Claude); a timeout falls back to regex / no summary |
| `ANTHROPIC_API_KEY` | `llm.py` | unset | only with `LLM_PROVIDER=anthropic` | Claude API key. **On its own it no longer enables Claude** |
| `ANTHROPIC_MODEL` | `llm.py` | `claude-haiku-5-5` | no | Claude model id (with `LLM_PROVIDER=anthropic`) |
| `CRITERIA_PATH` | `criteria_manager` | `backend/criteria.yaml` | no | Alternate criteria registry |
| `CORS_ORIGINS` | `main.py` | `http://localhost:3000` | no | Comma-separated allowed origins |
| `DATABASE_URL` | `db.py` | `sqlite:///./turnkey.db` (relative to `backend/`) | no | Run-history database |
| `API_ORIGIN` | frontend `next.config.ts` (server-side) | `http://localhost:8000` | no | Where the Next.js dev server proxies `/api/v1`, `/static`, `/health` |

**No `NEXT_PUBLIC_` variables exist.** The browser only calls relative URLs, and `API_ORIGIN` is
read at build/dev-server time by `next.config.ts`, so it is never exposed to client code. Never put
a secret in a `NEXT_PUBLIC_` variable.

## Vexcel key and licensed imagery

- **Header only, backend only.** The key is sent only in the `X-API-KEY` header from the backend. The
  browser never calls Vexcel: the backend downloads imagery into `backend/static/vexcel-cache/` and
  serves it from `/static/vexcel-cache/...`, so the key never appears in a URL, page or bundle.
- **Never logged.** Failure messages are redacted (`_redact` replaces the key with `***`) before they
  are logged or stored in the cache's `meta.json`; startup logs show only modes.
  `tests/test_vexcel.py::test_api_key_never_logged` and `test_request_shape_and_key_only_in_header`
  check this.
- **Licensed imagery stays local.** `backend/static/vexcel-cache/` is gitignored: Vexcel imagery and
  API responses must not be committed or redistributed. Only derived facts (numbers, a box) are
  snapshotted into `backend/fixtures/observations.json`. Live imagery is shown with the attribution
  "© Vexcel Imaging US, Inc.".
- **Rotate pasted keys.** If a key was ever pasted into a chat, issue, screenshot, terminal recording or
  commit, treat it as leaked and ask the sponsor to rotate it. Don't show `backend/.env` on screen
  during the demo.
- **Expiry and geofence.** The hackathon key works only for Los Angeles and Houston and expires
  2026-12-01. After expiry, already-cached properties keep working (no calls are made); anything else
  falls back to placeholders.

## Git hygiene

`.gitignore` excludes `backend/.env`, `backend/.env.local`, `frontend/.env.local`,
`backend/static/vexcel-cache/`, `backend/venv/`, `frontend/node_modules/`, `frontend/.next/`,
`backend/*.db` (including `turnkey.db`) and caches. Only `.env.example` (placeholders) is committed.
The test suite pins `DATABASE_URL` to a temp file, forces mock mode, sets `LLM_PROVIDER=none` and blanks
every API key (`tests/conftest.py`); Vexcel and LLM tests use fake HTTP layers and a temp cache dir, so
tests never touch the network, a running Ollama, your real DB or your cache.

## Practices in the code

- Keys are never logged; startup logs show only modes (`mock`/`live`, parser `regex`/`ollama`/`claude`,
  the LLM label) and the DB URL.
- Live provider calls use HTTPS base URLs; every outbound call has an explicit timeout; Claude calls have no retries. Every failure falls back.
- **The local LLM keeps data on the machine.** With the default `LLM_PROVIDER=ollama` the requirement
  text and the ranking digest go only to Ollama on `localhost`; nothing is sent to a third-party AI
  service. Only `LLM_PROVIDER=anthropic` sends them to Anthropic. Ollama has no auth, so keep it bound to
  localhost (its default).
- LLM output is treated as untrusted: parser fields are type- and range-checked, and the summary is
  rejected if it cites a dollar figure, score or property id that is not in the computed result. React
  renders it as escaped text.
- CORS allows only `CORS_ORIGINS`. In normal use the frontend goes through the same-origin Next.js
  proxy, so CORS matters only for direct API calls.
- Input is validated by Pydantic (422) and property / business type ids are checked (404 / 400).
  SQL goes through SQLModel (parameterized). Vexcel cache folder names are sanitized property ids.
- The drafted landlord letter is plain text rendered by React (escaped), not HTML.

## Out of scope for the hackathon

Authentication and authorization (anyone who can reach the API can read stored analyses by id),
rate limiting, and HTTPS termination. Add these before any public deployment (e.g. AWS behind
an ALB/API Gateway). A public deployment would also need Vexcel's terms for serving cached imagery.
