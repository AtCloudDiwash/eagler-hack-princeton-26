# Installation

EagleEye has two parts:

| Part | Tech | Port |
|---|---|---|
| `backend/` | Python 3.12, FastAPI, LangChain Deep Agents, SQLite | 8000 |
| `frontend/` | Next.js 15, TypeScript, Tailwind, MapLibre GL, Motion | 3000 (Docker) / any for dev |

All LLM decisions (query parsing, every Deep Agent step, the final recommendation) run through a
**fallback chain on your machine**: the **Codex CLI** (your Codex / ChatGPT login) → the **Claude Code CLI**
(your Claude login) → a local **Ollama** model. If Codex is out of usage, the app switches to Claude Code,
then Ollama, automatically. The app stores no LLM API key; each CLI keeps its own login. Data-source keys (Vexcel etc.) live in `backend/.env`; the
frontend holds no secrets.

---

## 1. Prerequisites

| Need | For | Install |
|---|---|---|
| **Codex CLI**, logged in | LLM (first choice) | The ChatGPT desktop app bundles it (auto-detected), or `npm install -g @openai/codex`. Then `codex login`. |
| **Claude Code CLI**, logged in | LLM fallback #1 | `npm install -g @anthropic-ai/claude-code` (or the native installer), then `claude auth login`. |
| **Ollama** + `qwen3:8b` | LLM fallback #2 (local) | https://ollama.com/download, then `ollama pull qwen3:8b`. |
| **Docker Desktop** (Engine ≥ 24, Compose ≥ 2.24) | Option A | https://www.docker.com/products/docker-desktop |
| **Python 3.12** and **Node.js 20+** | Option B | `brew install python@3.12 node` (macOS) |

Check Codex:
```bash
codex login status        # "Logged in using ChatGPT" (or API key)
```
If `codex` isn't on your PATH but the ChatGPT app is installed, the backend finds the bundled CLI at
`/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex` automatically.

Codex calls count against your Codex / ChatGPT plan usage. A full analysis makes roughly 25–40 short calls.

## 2. Configure

```bash
cp backend/.env.example backend/.env
```

| Variable | Required? | Notes |
|---|---|---|
| `VEXCEL_API_KEY` | Recommended | Vexcel API 2.0 key (sent as `X-API-KEY`). The hackathon key works in **Los Angeles and Houston** only. Without it, searches use OpenStreetMap footprints (or demo mode, below). |
| `LLM_PROVIDERS` | No | Fallback order, default `codex,claude,ollama`. Remove one to skip it. |
| `LLM_COOLDOWN_S` | No | How long an out-of-usage / logged-out provider is skipped (default 1200 s). |
| `CODEX_MODEL` | No | Empty = the model in your `~/.codex/config.toml`. |
| `CODEX_REASONING_EFFORT` | No | `low` (default, fast) · `medium` · `high`. |
| `CODEX_BIN` | No | Path to the CLI if it isn't auto-detected. |
| `CODEX_MAX_CONCURRENCY` | No | Parallel Codex calls (default 4); agents run concurrently. |
| `CLAUDE_MODEL` | No | Claude Code model: `sonnet` (default), `opus`, `haiku` or a full id. |
| `CLAUDE_CODE_OAUTH_TOKEN` | Docker only | Lets Claude Code work inside the container (`claude setup-token`); or set `ANTHROPIC_API_KEY`. |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | No | Default `http://localhost:11434`, `qwen3:8b` (Docker uses `host.docker.internal`). |
| `CENSUS_API_KEY` | No | Free key from https://api.census.gov/data/key_signup.html; enables tract demographics. |
| `MATTERPORT_API_KEY` / `_SECRET` | No | Matterport API token id / secret. Enables the interior agent for tours linked on the building panel (the 3D tour embeds without them). Offline: `python scripts/record_matterport_fixture.py <tour url>`. |
| CoStar kit (file, not a key) | No | Rentable area, spaces for lease, asking rents, and the building record the agents use (year built, class, parking spaces, sprinklers, zoning, prior build-out). Run `cd backend && .venv/bin/python scripts/build_costar_index.py ~/Downloads/costar-hackathon-kit` once; writes `backend/fixtures/costar_index.json` (gitignored). |
| `MATTERPORT_SANDBOX_API_KEY` / `_SECRET` | No | Optional sandbox token (sees only the account's demo model). Use it for development and `tests/test_matterport_contract.py`, which checks our GraphQL queries still validate; keep the full token for the demo machine only (Matterport tokens can make purchases). |
| `AGENT_MAX_MODEL_CALLS`, `AGENT_TIMEOUT_S` | No | Bounds on each agent's investigation. |
| `ANALYSIS_TIMEOUT_S` | No | Deadline for a whole analysis (default 900 s); agents, follow-ups and the narrative fit inside it. |

Never commit `backend/.env`; it is gitignored and excluded from Docker images.

How the backend calls Codex: `codex exec` in non-interactive mode, ephemeral (no session files), read-only
sandbox in an empty temp folder, ignoring your personal Codex config/plugins, with a JSON schema that forces
structured answers. See `backend/services/codex_chat.py`.

---

## Option A: Docker Compose

1. Make sure you're logged in to Codex on the host (`codex login status`).
2. Build and start:
   ```bash
   docker compose up --build
   ```
3. Open **http://localhost:3000**. The API is at http://localhost:8000 (`/api/health` shows the Codex login
   and Vexcel status).

The backend image contains the Linux Codex and Claude Code CLIs. Codex uses your login by mounting your
`~/.codex` folder into the container (read-write, because Codex refreshes its token there). Claude Code's
macOS login lives in the Keychain, which a container can't read, so set `CLAUDE_CODE_OAUTH_TOKEN` (from
`claude setup-token`) or `ANTHROPIC_API_KEY` in `backend/.env` to use it in Docker; otherwise it is skipped.
Ollama runs on your host and is reached at `host.docker.internal:11434`. Only run this image on machines
you trust with these logins. Use a different folder with
`CODEX_HOME_DIR=/path/to/codex-home docker compose up`.

**Ports in use?**
```bash
FRONTEND_PORT=3005 BACKEND_PORT=8005 docker compose up --build
```
(The frontend is rebuilt with the matching backend URL and CORS is updated automatically.)

Useful commands:
```bash
docker compose logs -f backend      # watch agent activity
docker compose down                 # stop
docker compose down -v              # stop and delete the database/cache volume
```

---

## Option B: Run locally (development)

```bash
# Backend
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --port 8000
```

```bash
# Frontend (second terminal)
cd frontend
npm install
cp .env.example .env.local          # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev -- -p 3001              # http://localhost:3001
```

Run the backend **without** `--reload` while analyses are running: a reload restarts the server and
interrupts in-progress investigations (they are marked failed).

If you serve the frontend on a port other than 3000/3001, add its origin to `CORS_ORIGINS` in `backend/.env`.

---

## 3. Verify

```bash
curl http://localhost:8000/api/health
# {"llm":{"ok":true,"provider":"codex","model":"<your model>",...},"vexcel":"live",...}

cd backend && .venv/bin/python -m pytest -q        # unit tests (Codex adapter tested with a fake CLI, offline)
cd frontend && npx tsc --noEmit && npm run lint     # frontend checks
```

Then in the UI: search **"I want to open a 40-seat restaurant in Houston"**, pick a building, adjust the
neighborhood radius, and click **Analyze This Property**. A full analysis typically takes 1–3 minutes;
the live view shows each agent's tool calls as they happen.

## Optional: demo mode without a Vexcel key

Vexcel responses are licensed, so the demo sample is not in the repository. With a key, record it once:
```bash
cd backend && .venv/bin/python scripts/record_demo_fixture.py
```
Afterwards, removing `VEXCEL_API_KEY` switches downtown-Houston searches to the recorded sample (labelled DEMO in the UI).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Badge shows **Claude** or **Ollama** (amber dot) | Codex is out of usage or logged out, so a fallback is in use; hover the badge for each provider's status. Codex is retried after `LLM_COOLDOWN_S`. |
| `/api/health` shows `llm.ok: false` | Every provider is unavailable; `llm.providers` lists why for each (not installed, not logged in, usage limit, Ollama not running). |
| "Codex CLI not found" | Install Codex or the ChatGPT app, or set `CODEX_BIN` to the binary path. |
| `llm.ok: false`, "Not logged in" | Run `codex login` on the host (Docker uses the same `~/.codex`). |
| Analyses fail with "codex exec failed" | Run `codex exec "say hi"` in a terminal to see the error (usage limit, expired login, network). |
| Analyses are slow | Keep `CODEX_REASONING_EFFORT=low`; raise `CODEX_MAX_CONCURRENCY` if your plan allows more parallel requests. |
| "OpenStreetMap places unavailable" | The public Overpass API is overloaded (502/504). The app retries and caches; search again in a minute. Agents report this data as unknown, never as zero. |
| Searches outside LA/Houston show no roof data | Expected: the Vexcel key is geofenced; footprints come from OpenStreetMap. |
| Browser shows "Can't reach the backend" | Check `NEXT_PUBLIC_API_URL` (dev) or `BACKEND_PORT` (Docker), and `CORS_ORIGINS`. |
