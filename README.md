# Turnkey Matchmaker

Find and vet a commercial building for a specific business. Describe what you want to open, pick a
building on a live Vexcel aerial map, and a team of local AI agents investigates whether that building
suits *your* purpose, with every finding tied to evidence.

```
User query ─▶ Vexcel discovery ─▶ map ─▶ select building ─▶ Vexcel JSON + neighborhood
          ─▶ multi-agent investigation (local Codex CLI) ─▶ Python scoring ─▶ dynamic dashboard ─▶ compare
```

## Run it

Full instructions, including **Docker Compose** (`docker compose up --build`), are in [INSTALLATION.md](INSTALLATION.md).

Prerequisites: Python 3.12, Node 20+, and at least one LLM provider on this machine. The fallback chain
tries them in order: the **Codex CLI** (`codex login`; the ChatGPT desktop app's bundled CLI is
auto-detected), the **Claude Code CLI** (`claude auth login`), then **Ollama** (`ollama pull qwen3:8b`).

```bash
codex login status                # Codex (first choice)
claude auth status                # Claude Code (fallback #1)
ollama list                       # Ollama (fallback #2)

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

**LLM fallback chain:** `backend/services/llm.py` returns a `FallbackChat` that tries **Codex CLI →
Claude Code CLI → Ollama** (`LLM_PROVIDERS`). The CLI adapters (`codex_chat.py`, `claude_chat.py`, shared
`cli_chat.py`) run one-shot, tool-less, schema-constrained calls in an empty temp folder; Deep Agents' tools
are described in the prompt and the CLI answers with schema-validated tool calls, which LangGraph executes
as with any provider. A provider that hits a usage limit is skipped for a cooldown, every analysis records
which provider served how many calls, and switches appear in the live log. Usage counts against your plans.

## The flow

1. **Query → intent.** `services/intent.py`: rules plus Codex (schema-constrained JSON) extract business type,
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

## Agents (`backend/agents/`, LangChain Deep Agents on the Codex CLI)

| Agent | Investigates | Tools (each result becomes evidence `E#`) |
|---|---|---|
| `vexcel_agent.py` | Building fit from aerial AI data; what imagery can't tell | overview, size fit, roof condition/defects/equipment, site paving, neighbor comparison, imagery date, raw field lookup, recorded CoStar building facts |
| `neighborhood_agent.py` | Demand, competition, access, area fit, at radii chosen for the business | place counts by group/radius (OSM), Vexcel building mix, transit & parking, Census demographics |
| `compliance_agent.py` | Permitted use, parking minimums, health/medical rules, ADA, CO | jurisdiction, permitted use, parking computation (CoStar parking count when recorded), use requirements, accessibility signals (stories, elevators, year built, suite floor), space program, recorded building facts (verified rule set only) |
| `cost_agent.py` | Feasibility; which conversion items the evidence triggers | rent band, cost items, deterministic `estimate_costs`, recorded facts (prior same-use build-out, CAM) |
| `matterport_agent.py` | Interior from a linked 3D scan: room mix, restrooms, ceiling heights, doors and windows, measured area | scan identity (is this scan the space? distance, suite, amenity check — `services/scan_identity.py`), overview, list rooms, rooms of a type, keyword search (rooms, tags, labels, notes), ceiling heights with measured coverage, doorways (ADA 32" clear, wide/dock doors), windows, area vs. need. Tools are offered only when the scan has that data. Skipped with open interior questions (including the user's interior needs) when there is no tour, no interior data, or the linked scan shows another building |

`agents/base.py` is the shared harness. It:
- removes Deep Agents' file, shell and sub-agent tools so each agent only sees its domain tools;
- registers every tool result as evidence, and trims oversized tool output for the model (the evidence keeps everything);
- refuses repeated calls (atomically, even for parallel tool calls) and enforces a per-agent tool budget, with a model-call cap and a timeout that fits the analysis deadline;
- requests structured output, accepts a JSON-text report, and falls back to a schema-constrained extraction that gets the same metric definitions; a timed-out agent keeps its conversation and evidence, and its rescued report is marked `partial`;
- validates every report: a citation counts only if that agent saw the evidence (its own results, the engine's verified context, or ids the engine shared with it), a non-unknown status only counts evidence that carries data, and every assigned metric and owned need gets an entry (`unknown` when not reported);
- takes the LLM as a parameter (`run_agent(..., model=...)`), so `tests/test_reliability.py` drives agents with a scripted fake model;
- streams progress events to the UI.

A scan only counts as showing the listed space ("verified") when it is near the building, names the building or
suite, was captured within 3 years (`processing.processingCompletedAt`; `created` is when the model joined the
account) and, when both are known, is on the listed suite's floor. Older, other-floor and whole-building scans are
"likely": building-level context, never inputs to size, interior or accessibility verdicts. Before a demo, run
`scripts/record_matterport_fixture.py --fallback --linked` to keep safety-net copies of the scans your saved buildings
use; they are served only when the live API fails, so the UI keeps showing live data.

`services/building_facts.py` merges the CoStar building record and Vexcel attributes into named facts with a
source and confidence (year built, class, condition, stories, ceiling height, elevators, sprinklers, zoning,
parking spaces, prior build-out, CAM…). Recorded CoStar values win over aerial estimates.

What makes the agents reason rather than summarize:
- **Purpose-specific metric briefs.** Each agent gets its metrics for this business, each with a "why it matters for you" note and a status guide.
- **Interpreted tool results.** Tools return evidence with notes on scales and detection limits, e.g. that "0 AC units detected" is not "no HVAC".
- **Explicit rules.** Agents must cite evidence, separate facts from inferences and assumptions, use "unknown" when evidence is insufficient, and suggest follow-ups.

## Orchestration (`backend/multi_agent_engine.py`)

1. **Context.** Gather property, neighborhood, census and jurisdiction concurrently.
2. **Plan.** Decide which agents run and why; Vexcel is skipped without data, Matterport without a tour.
3. **Phase 1.** Vexcel, Neighborhood, Compliance (+ Matterport) run concurrently. **Phase 2:** the Cost Agent receives their findings, because its costs depend on them.
4. **Validation.**
   - Citations an agent never saw are stripped and flagged.
   - **Data-settled verdicts take precedence over agent opinions** (`services/verdicts.py`). A metric may name a
     `resolver` in `metrics.yaml`; resolvers compute the status once per analysis from verified rules, the cost
     engine, the CoStar record, aerial and interior data, at the user's program size (never at a size an agent
     chose). An agent may be *more* cautious than a verdict, never less; on an override the rule's reason becomes
     the rationale and the agent's view is kept as a note, and findings that argue the opposite are dropped.
     Resolvers today: permitted use, parking requirement, size fit, occupancy/code fit, roof condition, rooftop
     HVAC, occupancy cost, conversion risk, competition without place data, accessibility, and a cap for interior
     layout.
   - **Accessibility uses verified data only**: the CoStar record (listed suite's floor, stories, elevators, year
     built) and door widths measured in a Matterport scan verified to show the listed suite. Aerial estimates and
     agent judgment never set it; without verified data it is `unknown`.
   - The merge is a pure function of (agent assessments, verdicts), so re-merging after follow-ups is consistent.
   - A blocker without evidence is downgraded, so "not detected" never blocks.
   - A must-have need the evidence shows is unmet caps the verdict at "Recommended with conditions".
5. **Conflicts.** Cross-agent contradictions are recorded with a resolution.
6. **Follow-ups.** For unknown or unevidenced high-weight metrics that no verdict settles, the engine simulates whether resolving them would flip the verdict. If so, it sends the owning agent a follow-up about that one metric (max 2, budget 3 tools, earlier tool results reused; skipped near the deadline).
7. **Scoring (Python only).** Status → points, weighted by business. Confidence is the share of weight with verified evidence. Verdict thresholds live in `services/scoring.py`.
8. **Narrative.** A Codex-written summary grounded on the scored result; if that fails, a deterministic template is used.

An agent that fails or times out never sinks the analysis: its metrics become `unknown` and confidence drops.
Only when every LLM provider is exhausted (usage limit, not installed, not logged in) does the analysis stop;
a call that fails on every provider for another reason (bad JSON, a timeout) fails just that agent. The whole
analysis runs inside `ANALYSIS_TIMEOUT_S`, and cancelled CLI calls are killed.

## Space program: what the request implies (`services/program.py`)

The query is turned into a deterministic **space program** before any building is chosen, so the user's
size, headcount and stated needs drive the whole analysis:

| From the request | Becomes |
|---|---|
| Business-specific counts: seats (restaurant), operatories (dental), class size or members (gym), people (office), staff | Target / min / max sq ft (`program.drivers` in `business_types.yaml`) |
| Size + headcount | Occupant load (IBC Table 1004.5 factors, never below the people stated) → occupancy group (A-2 / A-3 / B / M; assembly under 50 people is Group B) → exits, restrooms (IPC Table 2902.1), sprinkler triggers (IBC §903.2) |
| Business type | Suitable building types, ground floor required/preferred, minimum ceiling height, typical build-out months |
| Needs (`config/needs.yaml`): parking, ADA, drive-thru, patio, alcohol, late hours, loading, kitchen, showers, X-ray, high ceilings… | Must-have or nice-to-have, each routed to the agent that checks it |
| Timeline, buy vs. lease, places to be near / avoid | Timeline vs. build-out check; context for every agent |

The search response returns the program (shown as "What you need"), the pre-screen ranks candidates
against it, every agent's prompt includes it (with the needs it owns), the Compliance Agent's
`check_space_program` tool compares it with the building, and the dashboard's **Your needs** tab shows
what was asked for next to how the building measures up. Code values are 2021 IBC/IPC model-code
planning checks with citations (`config/occupancy_codes.yaml`); local amendments decide.

## Configuration-driven evaluation (`backend/config/`)

- `metrics.yaml`: the metric registry. Each entry has a name, group, common/dynamic category, owner agent, evidence hint and status guide, plus `hard_block`, an optional deterministic `resolver` and the `evidence_tools` that support it.
- `business_types.yaml`: per business, the metrics with weights and reasons, sizing, catchment radius, place roles and keywords. Restaurant, dental clinic, gym, office and retail are included.
- `place_groups.yaml`: OSM tag → place group mapping.
- `jurisdictions.yaml`: verified rules with citations (Houston researched; LA/unknown cities → `unknown` with where to check).
- `costs.yaml`: rent bands, base fit-out, adders and soft costs. All are documented planning assumptions.
- `needs.yaml`: needs a user can state (keywords, owner agent, what each triggers, and an optional deterministic `check`, e.g. `paved_area` with `min_paved_sqft`).
- `occupancy_codes.yaml`: exits, restroom fixtures and sprinkler triggers per occupancy group, with citations.

**Adding a metric or business type is a YAML edit.** Agents pick up their metrics from the registry and the dashboard renders whatever metrics a result contains, so neither needs code changes.

## Data sources & honesty

| Source | Status |
|---|---|
| Vexcel `/ortho/tile`, `/property/extract` | Live (key geofenced to Los Angeles + Houston) or labelled demo sample |
| OpenStreetMap Nominatim / Overpass | Geocoding, places (volunteer-mapped; counts are lower bounds) |
| US Census geocoder + ACS | Tract always; demographics with a free `CENSUS_API_KEY` |
| Verified rule set | Houston (no zoning, §26-492 parking, health/grease/ADA); others report `unknown` |
| CoStar (sponsor kit) | Rentable Building Area (RBA; GLA for retail), spaces on the market with each suite's rentable sq ft, floor and asking rent, and CoStar's Matterport scans. Matched to buildings by location; listed properties near the search are added as candidates; a net asking rent replaces the planning rent band in the cost engine. Build the index once: `python scripts/build_costar_index.py [kit path]` (licensed, gitignored). Kit snapshot, not live availability. |
| Building size fields | `area_sqft` = Vexcel **building footprint** (outline from above, ~one floor), `floor_area_est_sqft` = footprint × stories, `parcel_sqft` = the lot, `rentable_sqft` = CoStar RBA/GLA, `best_space.sqft` = the listed suite that fits |
| Matterport Model API (GraphQL) | Paste a tour URL on the building panel. The 3D tour always embeds; interior data needs a token with access to the model, or a scan recorded with `scripts/record_matterport_fixture.py` (offline). Dimensions/objects are Property Intelligence (Enterprise) fields and degrade gracefully |

Cost figures are ranges from documented bands, not quotes. Compliance output is decision support, not
legal advice; verify with the city.
