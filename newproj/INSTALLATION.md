# Installation

Turnkey Matchmaker has two parts:

| Part | Tech | Port |
|---|---|---|
| `backend/` | Python 3.12, FastAPI, LangChain Deep Agents, SQLite | 8000 |
| `frontend/` | Next.js 15, TypeScript, Tailwind, MapLibre GL, Motion | 3000 (Docker) / any for dev |

All LLM decisions (query parsing, every Deep Agent step, the final recommendation) run through the
**Codex CLI on your machine**, using **your own Codex / ChatGPT login**. The app stores no LLM API key:
Codex keeps its credentials in `~/.codex`. Data-source keys (Vexcel etc.) live in `backend/.env`; the
frontend holds no secrets.

---

## 1. Prerequisites

| Need | For | Install |
|---|---|---|
| **Codex CLI**, logged in | All agent reasoning | The ChatGPT desktop app bundles it (auto-detected), or `npm install -g @openai/codex`. Then `codex login` (ChatGPT account or API key). |
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
| `CODEX_MODEL` | No | Empty = the model in your `~/.codex/config.toml`. |
| `CODEX_REASONING_EFFORT` | No | `low` (default, fast) · `medium` · `high`. |
| `CODEX_BIN` | No | Path to the CLI if it isn't auto-detected. |
| `CODEX_MAX_CONCURRENCY` | No | Parallel Codex calls (default 4); agents run concurrently. |
| `CENSUS_API_KEY` | No | Free key from https://api.census.gov/data/key_signup.html; enables tract demographics. |
| `MATTERPORT_API_KEY` / `_SECRET` | No | Enables the optional interior agent (needs a tour linked to the property). |
| `AGENT_MAX_MODEL_CALLS`, `AGENT_TIMEOUT_S` | No | Bounds on each agent's investigation. |

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

The backend image contains the Linux Codex CLI (`@openai/codex`). It uses your login by mounting your
`~/.codex` folder into the container (read-write, because Codex refreshes its token there). Only run this
image on machines you trust with that login. Use a different folder with
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
| `/api/health` shows `llm.ok: false`, "Codex CLI not found" | Install Codex or the ChatGPT app, or set `CODEX_BIN` to the binary path. |
| `llm.ok: false`, "Not logged in" | Run `codex login` on the host (Docker uses the same `~/.codex`). |
| Analyses fail with "codex exec failed" | Run `codex exec "say hi"` in a terminal to see the error (usage limit, expired login, network). |
| Analyses are slow | Keep `CODEX_REASONING_EFFORT=low`; raise `CODEX_MAX_CONCURRENCY` if your plan allows more parallel requests. |
| "OpenStreetMap places unavailable" | The public Overpass API is overloaded (502/504). The app retries and caches; search again in a minute. Agents report this data as unknown, never as zero. |
| Searches outside LA/Houston show no roof data | Expected: the Vexcel key is geofenced; footprints come from OpenStreetMap. |
| Browser shows "Can't reach the backend" | Check `NEXT_PUBLIC_API_URL` (dev) or `BACKEND_PORT` (Docker), and `CORS_ORIGINS`. |
