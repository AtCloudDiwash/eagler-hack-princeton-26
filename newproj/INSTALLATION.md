# Installation

Turnkey Matchmaker has two parts:

| Part | Tech | Port |
|---|---|---|
| `backend/` | Python 3.12, FastAPI, LangChain Deep Agents, SQLite | 8000 |
| `frontend/` | Next.js 15, TypeScript, Tailwind | 3000 (Docker) / any for dev |

All AI inference runs locally through **Ollama**. Every API key lives in `backend/.env`; the frontend
holds no secrets.

---

## 1. Prerequisites

| Need | For | Install |
|---|---|---|
| **Ollama** + a tool-calling model | All agent reasoning | https://ollama.com/download, then `ollama pull qwen3:8b` |
| **Docker Desktop** (Docker Engine ≥ 24, Compose ≥ 2.24) | Option A | https://www.docker.com/products/docker-desktop |
| **Python 3.12** and **Node.js 20+** | Option B | `brew install python@3.12 node` (macOS) |

`qwen3:8b` needs ~6 GB of RAM/VRAM. `qwen3:14b` reasons better but is ~2x slower; set `OLLAMA_MODEL` to switch.

## 2. Configure credentials

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env`:

| Variable | Required? | Notes |
|---|---|---|
| `VEXCEL_API_KEY` | Recommended | Vexcel API 2.0 key (sent as `X-API-KEY`). The hackathon key works in **Los Angeles and Houston** only. Without it the app uses OpenStreetMap footprints (or demo mode, below). |
| `OLLAMA_MODEL` | No | Default `qwen3:8b`. |
| `OLLAMA_BASE_URL` | No | Default `http://localhost:11434`. Docker Compose overrides this automatically. |
| `CENSUS_API_KEY` | No | Free key from https://api.census.gov/data/key_signup.html; enables tract demographics. |
| `MATTERPORT_API_KEY` / `_SECRET` | No | Enables the optional interior agent (needs a tour linked to the property). |
| `AGENT_MAX_MODEL_CALLS`, `AGENT_TIMEOUT_S` | No | Bounds on each agent's investigation. |

Never commit `backend/.env`; it is gitignored and excluded from Docker images.

---

## Option A: Docker Compose (recommended)

1. Start Ollama on your machine (`ollama serve`, or open the Ollama app) and pull the model:
   ```bash
   ollama pull qwen3:8b
   ```
2. Build and start:
   ```bash
   docker compose up --build
   ```
3. Open **http://localhost:3000**. The API is at http://localhost:8000 (`/api/health` shows Ollama/Vexcel status).

The backend reaches your host's Ollama at `host.docker.internal:11434`. Analyses and caches persist in
the `turnkey-data` volume.

**Ports in use?** Change them without editing files:
```bash
FRONTEND_PORT=3005 BACKEND_PORT=8005 docker compose up --build
```
(The frontend is rebuilt with the matching backend URL and CORS is updated automatically.)

**Ollama inside Docker instead** (no host install; CPU-only on macOS, so expect much slower analyses):
```bash
OLLAMA_BASE_URL=http://ollama:11434 docker compose --profile ollama up --build
```
The `ollama-pull` service downloads the model on first start (several GB).

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
# {"ollama":{"ok":true,"model":"qwen3:8b",...},"vexcel":"live",...}

cd backend && .venv/bin/python -m pytest -q        # backend unit tests
cd frontend && npx tsc --noEmit && npm run lint     # frontend checks
```

Then in the UI: search **"I want to open a 40-seat restaurant in Houston"**, pick a building, adjust the
neighborhood radius, and click **Analyze This Property**. An analysis takes about 2.5–5 minutes on an
M-series Mac with `qwen3:8b`; the live view shows each agent's tool calls as they happen.

## Optional: demo mode without a Vexcel key

Vexcel responses are licensed, so the demo sample is not in the repository. With a key, record it once:
```bash
cd backend && .venv/bin/python scripts/record_demo_fixture.py
```
Afterwards, removing `VEXCEL_API_KEY` switches downtown-Houston searches to the recorded sample (labelled DEMO in the UI).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/api/health` shows `ollama.ok: false` | Start Ollama and `ollama pull <OLLAMA_MODEL>`. In Docker, make sure Ollama listens on the host (default app settings do). |
| Analyses are slow | Ollama serves one request at a time by default. Start Ollama with `OLLAMA_NUM_PARALLEL=3` so the three phase-1 agents run truly in parallel. |
| "OpenStreetMap places unavailable" | The public Overpass API is overloaded (502/504). The app retries and caches; search again in a minute. Agents report this data as unknown, never as zero. |
| Searches outside LA/Houston show no roof data | Expected: the Vexcel key is geofenced; footprints come from OpenStreetMap. |
| Browser shows "Can't reach the backend" | Check `NEXT_PUBLIC_API_URL` (dev) or `BACKEND_PORT` (Docker), and `CORS_ORIGINS`. |
