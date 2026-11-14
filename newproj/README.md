# Turnkey Matchmaker

Find and vet a commercial building for a specific business. Describe what you want to open, pick a
building on a live Vexcel aerial map, and a team of local AI agents investigates whether that building
suits *your* purpose, with every finding tied to evidence.

```
User query ─▶ Vexcel discovery ─▶ map ─▶ select building ─▶ Vexcel JSON + neighborhood
          ─▶ multi-agent investigation (Ollama) ─▶ Python scoring ─▶ dynamic dashboard ─▶ compare
```

## Run it

Full instructions, including **Docker Compose** (`docker compose up --build`), are in [INSTALLATION.md](INSTALLATION.md).

Prerequisites: Python 3.12, Node 20+, [Ollama](https://ollama.com) with a tool-calling model.

```bash
ollama pull qwen3:8b

# backend (FastAPI, port 8000)
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # put VEXCEL_API_KEY here (all keys live in the backend)
.venv/bin/uvicorn main:app --port 8000

# frontend (Next.js) in another terminal
cd frontend
npm install
cp .env.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000 (no secrets)
npm run dev -- -p 3001          # http://localhost:3001
```

Tests: `cd backend && .venv/bin/python -m pytest -q`; `cd frontend && npx tsc --noEmit && npm run lint && npm run build`.

**Credentials:** `backend/.env` only (see `backend/.env.example`). The frontend never sees an API key;
map tiles are proxied through `GET /api/tiles/{z}/{x}/{y}`.

**Speed tip:** Ollama serves one request at a time by default, so the three phase-1 agents take turns
(a full analysis takes ~3–5 min on an M-series Mac). Setting `OLLAMA_NUM_PARALLEL=3` for the Ollama
server lets them run truly in parallel.

## The flow

1. **Query → intent.** `services/intent.py`: rules plus Ollama (constrained JSON) extract business type,
   seats/sq ft, location and requirements.
2. **Discovery (no agents).** `services/discovery.py`: Vexcel has no listings or text search (checked
   against its OpenAPI spec), so discovery geocodes the place, pulls Vexcel parcels around it
   (`/property/extract`, `include=calculated` for roof height), keeps building types that suit the
   business and pre-screens them deterministically (type, size, roof, data). Outside the key's geofence
   (LA + Houston) it falls back to OpenStreetMap footprints and says so. No key → labelled demo mode
   from a recorded Houston sample (licensed data, gitignored; record it once with
   `backend/scripts/record_demo_fixture.py`).
3. **Select a building.** Readable key facts plus the complete Vexcel JSON, and a neighborhood view:
   Vexcel neighbor parcels plus OpenStreetMap places within an adjustable radius. The slow Overpass
   fetch is started for the whole search area at search time and cached in SQLite.
4. **Analyze.** `POST /api/analyses` stores a job in SQLite and runs `multi_agent_engine.py` in the
   background; the UI polls the live event log.
5. **Dashboard.** Verdict, score, confidence, business-specific metrics, agent reports, evidence and
   costs, plus a comparison view across analyses.

## Agents (`backend/agents/`, LangChain Deep Agents on Ollama)

| Agent | Investigates | Tools (each result becomes evidence `E#`) |
|---|---|---|
| `vexcel_agent.py` | Building fit from aerial AI data; what imagery can't tell | overview, size fit, roof condition/defects/equipment, site paving, neighbor comparison, imagery date, raw field lookup |
| `neighborhood_agent.py` | Demand, competition, access, area fit, at radii chosen for the business | place counts by group/radius (OSM), Vexcel building mix, transit & parking, Census demographics |
| `compliance_agent.py` | Permitted use, parking minimums, health/medical rules, ADA, CO | jurisdiction, permitted use, parking computation, use requirements, accessibility signals (verified rule set only) |
| `cost_agent.py` | Feasibility; which conversion items the evidence triggers | rent band, cost items, deterministic `estimate_costs` |
| `matterport_agent.py` | Interior (optional) | Skipped with explicit open questions when no credentials/tour |

`agents/base.py` is the shared harness. It:
- removes Deep Agents' file, shell and sub-agent tools so each agent only sees its domain tools;
- registers every tool result as evidence;
- refuses repeated calls and enforces a per-agent tool budget, with a model-call cap and timeout;
- requests structured output, accepts a JSON-text report, and falls back to Ollama constrained-JSON extraction;
- streams progress events to the UI.

What makes the agents reason rather than summarize:
- **Purpose-specific metric briefs.** Each agent gets its metrics for this business, each with a "why it matters for you" note and a status guide.
- **Interpreted tool results.** Tools return evidence with notes on scales and detection limits, e.g. that "0 AC units detected" is not "no HVAC".
- **Explicit rules.** Agents must cite evidence, separate facts from inferences and assumptions, use "unknown" when evidence is insufficient, and suggest follow-ups.

## Orchestration (`backend/multi_agent_engine.py`)

1. **Context.** Gather property, neighborhood, census and jurisdiction concurrently.
2. **Plan.** Decide which agents run and why; Vexcel is skipped without data, Matterport without a tour.
3. **Phase 1.** Vexcel, Neighborhood, Compliance (+ Matterport) run concurrently. **Phase 2:** the Cost Agent receives their findings, because its costs depend on them.
4. **Validation.**
   - Citations to nonexistent evidence are stripped and flagged.
   - **Verified rules and the cost engine take precedence over agent opinions.** An agent cannot mark use "permitted" when the rule result is unknown.
   - A blocker without evidence is downgraded, so "not detected" never blocks.
5. **Conflicts.** Cross-agent contradictions are recorded with a resolution.
6. **Follow-ups.** For unknown or unevidenced high-weight metrics, the engine simulates whether resolving them would flip the verdict. If so, it sends the owning agent a targeted follow-up (max 2, budget 3 tools).
7. **Scoring (Python only).** Status → points, weighted by business. Confidence is the share of weight with verified evidence. Verdict thresholds live in `services/scoring.py`.
8. **Narrative.** An Ollama summary grounded on the scored result; if that fails, a deterministic template is used.

An agent that fails or times out never sinks the analysis: its metrics become `unknown` and confidence drops.

## Configuration-driven evaluation (`backend/config/`)

- `metrics.yaml`: the metric registry. Each entry has a name, group, common/dynamic category, owner agent, evidence hint and status guide, plus `hard_block`.
- `business_types.yaml`: per business, the metrics with weights and reasons, sizing, catchment radius, place roles and keywords. Restaurant, dental clinic, gym, office and retail are included.
- `place_groups.yaml`: OSM tag → place group mapping.
- `jurisdictions.yaml`: verified rules with citations (Houston researched; LA/unknown cities → `unknown` with where to check).
- `costs.yaml`: rent bands, base fit-out, adders and soft costs. All are documented planning assumptions.

**Adding a metric or business type is a YAML edit.** Agents pick up their metrics from the registry and the dashboard renders whatever metrics a result contains, so neither needs code changes.

## Data sources & honesty

| Source | Status |
|---|---|
| Vexcel `/ortho/tile`, `/property/extract` | Live (key geofenced to Los Angeles + Houston) or labelled demo sample |
| OpenStreetMap Nominatim / Overpass | Geocoding, places (volunteer-mapped; counts are lower bounds) |
| US Census geocoder + ACS | Tract always; demographics with a free `CENSUS_API_KEY` |
| Verified rule set | Houston (no zoning, §26-492 parking, health/grease/ADA); others report `unknown` |
| CoStar listings / rents | Not connected; rent uses documented planning bands |
| Matterport | Optional; no tours linked in this build, so the agent reports interior questions as open |

Cost figures are ranges from documented bands, not quotes. Compliance output is decision support, not
legal advice; verify with the city.
