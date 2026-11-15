<img src="assets/brand/logo/eagleeye-logo-dark.png" alt="EagleEye logo" width="96" />

# EagleEye

**Find a commercial space that fits your business—before you sign the lease.**

Built for HackPrinceton Fall 2026, EagleEye helps small business owners investigate a location beyond its listing. Describe what you want to open, explore buildings on a map, and let a team of AI agents check the building, neighborhood, rules, interior, and likely costs. The result is a recommendation with supporting evidence, a confidence score, and questions to resolve before committing.

> “I want to open a 40-seat restaurant in Houston with a kitchen and parking.”

EagleEye turns that request into space requirements, finds candidate buildings, and evaluates each against what **your business** needs. It currently supports restaurants, dental clinics, gyms and fitness studios, offices, and retail stores.

[Getting started](#getting-started) · [How it works](#how-it-works) · [Data sources](#data-sources-and-availability) · [Project structure](#architecture-and-project-structure)

## Why EagleEye?

A low asking rent can hide an expensive conversion. A space might need a kitchen, additional restrooms, better access, or parking that the site cannot provide. EagleEye brings these questions into the search process so owners can compare the practical cost and feasibility of opening at different locations.

- **Search in plain English.** Include the business type, location, size or headcount, budget, and must-haves.
- **Refine through conversation.** Ask “make it 60 seats,” “only ground floor,” or “which two would you shortlist?” without starting over.
- **Explore the surroundings.** Find competitors, transit, parking, and nearby businesses; switch between aerial and street maps and 2D/3D views.
- **Investigate with evidence.** Watch the agents work, inspect their findings and sources, and see where information is missing.
- **Compare the options.** Review saved analyses side by side, including fit, confidence, requirements, and cost ranges.

## How it works

1. **Describe the business.** EagleEye extracts your intent and builds a space program: target area, occupancy, required facilities, and stated needs.
2. **Discover candidates.** It geocodes the location and ranks buildings using type, size, distance, roof data, and available evidence. Where a local CoStar index is available, it includes listed suites and their rentable area.
3. **Refine and select.** Adjust the request in chat, inspect a building and its neighborhood, and optionally link a Matterport tour.
4. **Choose an analysis mode.** **Quick** starts agents with pre-gathered evidence and keeps reports brief. **Deep report** lets agents choose what to investigate and adds targeted follow-ups when an unresolved question could change the recommendation. Runtime depends on the model and data services.
5. **Review the recommendation.** The dashboard shows a verdict, score, confidence, business-specific metrics, evidence, cost estimates, and outstanding questions.

### The agent team

| Agent | What it investigates |
|---|---|
| **Building / Vexcel** | Building size, roof condition, rooftop equipment, paving, and what aerial imagery can establish. |
| **Neighborhood** | Competition, demand, nearby places, transit, parking, demographics, and walking access. |
| **Compliance** | Permitted use, parking requirements, accessibility signals, and the space program against the available rule set. |
| **Interior / Matterport** | Rooms, measured area, ceiling heights, doors, and windows from a linked scan, when available. |
| **Cost** | Occupancy and conversion cost ranges, using the building evidence and a deterministic cost engine. |

In Deep mode, the building, neighborhood, compliance, and available interior investigations run concurrently. The Cost Agent then receives their findings. Quick mode starts cost work as soon as the building and compliance evidence is ready. Agents without the data they need are skipped, and the report records the gaps.

### Evidence, scoring, and uncertainty

The backend uses **LangChain Deep Agents on LangGraph**. Each agent gets domain-specific tools, with limits on model calls, tool calls, and execution time.

- Tool results are registered as evidence IDs such as `E1` and `E2`. Citations are checked against evidence the agent actually received.
- Verified rules and deterministic checks constrain agent assessments. Unsupported blockers are downgraded.
- Python computes scores, confidence, and cost ranges. Confidence reflects the share of weighted checks backed by evidence. The model writes the explanation from those results.
- Unknown information stays visible. For example, “no rooftop AC units detected” does not establish that a building has no HVAC.
- Missing or failed agent reports reduce confidence; the analysis can still complete with the remaining evidence. Exhausting every model provider stops the investigation.

## Getting started

The app has a **FastAPI backend** and a **Next.js frontend**. For local development, use **Python 3.12**, **Node.js 20+**, and at least one working model provider.

### 1. Configure a model provider

The default fallback order is **Codex CLI → Claude Code CLI → Ollama**. You only need one; the backend tries the next available provider if a call fails or a provider runs out of usage.

- **Codex CLI:** authenticate with `codex login`.
- **Claude Code CLI:** authenticate with `claude auth login`.
- **Ollama:** run Ollama locally and download the default model with `ollama pull qwen3:8b`.

Set `LLM_PROVIDERS` in `backend/.env` to change the order or select a single provider. CLI calls use your provider account and count toward its usage limits.

### 2. Start the backend

Run from the repository root:

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env` to configure your provider and any data-source credentials, then start the API from `backend/`:

```bash
.venv/bin/uvicorn main:app --port 8000
```

Keep the backend running without `--reload` during investigations: restarting the server interrupts active analyses.

### 3. Start the frontend

In a second terminal, from the repository root:

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev -- -p 3001
```

Open **[localhost:3001](http://localhost:3001)**. The frontend template points to `http://localhost:8000`; the default backend CORS settings allow frontend ports 3000 and 3001.

Check backend and provider status at **[localhost:8000/api/health](http://localhost:8000/api/health)**. Interactive API docs are available at **[localhost:8000/docs](http://localhost:8000/docs)**.

Try the restaurant example above, select a building, and start an analysis. To inspect a sample dashboard without running the backend or a model provider, use **[localhost:3001/analysis/demo](http://localhost:3001/analysis/demo)** while the frontend dev server is running. This sample route is disabled in production builds.

### Docker alternative

With Docker Compose and a model provider configured, run from the repository root:

```bash
cp backend/.env.example backend/.env
# Edit backend/.env with your settings before starting.
docker compose up --build
```

Open **[localhost:3000](http://localhost:3000)**. Compose starts both services and persists the database and downloaded datasets in volumes. It mounts your host's `~/.codex` directory for Codex authentication; Claude authentication inside Docker needs an OAuth token or API key. Ollama runs on the host.

See **[INSTALLATION.md](INSTALLATION.md)** for provider setup, Docker authentication, custom ports, optional data imports, and troubleshooting.

## Data sources and availability

All data-source credentials belong in **`backend/.env`**. The frontend only needs `NEXT_PUBLIC_API_URL`; Vexcel tiles are proxied through the backend so its key stays off the client.

| Source | What it adds | Availability |
|---|---|---|
| **Vexcel** | Aerial imagery, building footprints, roof condition, and site attributes. | Requires `VEXCEL_API_KEY`. The hackathon key is limited to Houston and Los Angeles. |
| **OpenStreetMap** | Geocoding, fallback building footprints, and nearby places. | No key required; public-service availability and mapping completeness vary. |
| **CoStar sponsor kit** | Building facts, rentable area, listed suites, asking rents, and linked tours. | Import a local kit with `backend/scripts/build_costar_index.py`; this is a recorded snapshot, not a live listing feed. |
| **Matterport** | Embedded tours and, with model access, interior measurements and room data. | Link a tour on the property panel. Interior API access uses `MATTERPORT_API_KEY` and `MATTERPORT_API_SECRET`; recorded scans are also supported. |
| **US Census / ACS / LODES** | Demographics, daytime workers, and employed residents. | ACS demographics use optional `CENSUS_API_KEY`; LODES datasets are downloaded and cached locally. |
| **OSRM / FEMA** | Walking routes and flood-zone context. | Public services, subject to availability. |
| **Verified jurisdiction rules** | Use, parking, and business-specific compliance checks. | Houston rules are included. Unresearched jurisdictions return unknowns with follow-up guidance. |

**Without a Vexcel key**, discovery falls back to OpenStreetMap footprints. Near downtown Houston, it first tries a recorded Vexcel demo fixture if one exists. Licensed Vexcel samples, CoStar records, and Matterport scans are excluded from Git and are not included in a fresh clone; recording and import instructions are in [INSTALLATION.md](INSTALLATION.md).

Building footprint, whole-building rentable area, and a listed suite's area are different measurements. EagleEye tracks those distinctions and prefers an appropriate listed suite when that evidence is available. A Matterport scan is checked for identity and freshness before its measurements can determine suite-specific verdicts.

Cost estimates are planning ranges from documented assumptions, not contractor quotes. Compliance findings support due diligence and still need verification with the relevant authority.

## Architecture and project structure

The frontend uses **Next.js 15, React 19, TypeScript, Tailwind CSS 4, MapLibre GL, and Motion**. The backend uses **Python, FastAPI, Pydantic, SQLite, LangChain, LangGraph, and Deep Agents**.

```text
frontend/                         Next.js app
  app/                            Discovery, analysis, demo, and comparison pages
  components/                     Map, chat, property panels, and report UI
  lib/                            Typed API client, shared types, and formatting
backend/                          FastAPI app
  main.py                         HTTP endpoints and analysis job creation
  multi_agent_engine.py           Orchestration, validation, and report assembly
  agents/                         Five domain agents and their shared harness
  services/                       Discovery, data integrations, models, scoring, costs
  config/                         YAML metrics, business types, needs, rules, costs
  scripts/                        Local data imports and fixture recording
  tests/                          Backend tests
assets/brand/                     EagleEye logos and presentation assets
legacy/                           Earlier prototype and its original design docs
INSTALLATION.md                   Detailed setup and troubleshooting
docker-compose.yml               Local two-service deployment
```

The browser talks to FastAPI over REST and polls the live analysis event log. SQLite stores searches, property data, analysis history, and cached responses. The model adapter layer implements the provider fallback chain in [`backend/services/llm.py`](backend/services/llm.py).

### Extending the evaluation

Start with [`backend/config/`](backend/config/):

| File | Purpose |
|---|---|
| `business_types.yaml` | Business sizing, metric weights, suitable buildings, and neighborhood criteria. |
| `metrics.yaml` | Metric definitions, agent ownership, evidence guidance, and deterministic resolvers. |
| `needs.yaml` | User requirements and the agents responsible for checking them. |
| `jurisdictions.yaml` | Researched local rules and their citations. |
| `occupancy_codes.yaml` | Model-code occupancy, exit, fixture, and sprinkler planning checks. |
| `costs.yaml` | Rent bands, fit-out assumptions, conversion items, and soft costs. |
| `place_groups.yaml` | OpenStreetMap tags grouped into useful place categories. |

Business types and metrics that use the existing tools and checks can be added through YAML. New data sources or evaluation logic need corresponding service or tool changes. The dashboard renders metrics from the analysis result.

## Development checks

From `backend/`, with its virtual environment installed:

```bash
.venv/bin/python -m pytest -q
```

From `frontend/`, with dependencies installed:

```bash
npx tsc --noEmit
npm run lint
npm run build
```

For setup issues, provider limits, missing map data, or connection errors, see the [installation troubleshooting guide](INSTALLATION.md#troubleshooting).
