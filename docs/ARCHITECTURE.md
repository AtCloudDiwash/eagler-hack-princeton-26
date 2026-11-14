# Architecture

The Turnkey Matchmaker system is divided into **Frontend**, **Backend**, and **AI/Agent** components, arranged as a monorepo.

- **Frontend (Next.js)**: User interface, written in React + TypeScript. Communicates with the backend via RESTful API. Responsibilities:
  - Collect user input (business type, requirements, location).
  - Display lists of properties and analysis results.
  - Render compliance and cost breakdown UIs.
  - Visualize overlays: highlight features on aerial images, embed Matterport viewer or static snapshots.
  - Implement dynamic criteria display (using the config).
  - Maintain state (selected property, analysis report).
  - Handle network errors (show friendly messages).

- **Backend (FastAPI)**: Serves as the core orchestrator and data processor. Responsibilities:
  - **API Layer**: Defines endpoints (see API_CONTRACT.md) for property search, analysis, user input handling.
  - **Data Models**: Pydantic/SQLModel schemas for properties, analysis results, criteria (see DATA_MODELS.md).
  - **Providers/Adapters**: Modules that interface with external data:
    - `providers/costar.py`: (Mock) fetch list of properties.
    - `providers/matterport.py`: (Mock) return details or image of interior spaces.
    - `providers/vexcel.py`: (Mock) fetch aerial images.
    - `providers/geocode.py`: (Optional) get lat/lng from address.
  - **Business Logic**:
    - **Agent Orchestration** (see AGENT_ORCHESTRATION.md): Sequence of steps: parse user query, fetch property data, analyze features, apply compliance & cost checks.
    - **Cost Engine** (see COST_ENGINE.md): Applies cost rules to estimate renovation expenses.
    - **Compliance Engine** (see COMPLIANCE_AGENT.md): Applies location-based rules to label PASS/RISK/UNKNOWN.
    - **Criteria Registry** (see CRITERIA_REGISTRY.md): Loads scoring criteria from config and computes scores.
  - **Database (SQLite)**: Stores any needed data (e.g. saved reports, user queries, if needed). For a hackathon MVP, minimal usage.
  - **Background Tasks**: For longer-running analysis (if needed). The API can return a job ID and allow polling status.
  - **Caching**: Cache results of expensive calls (e.g. provider APIs, analysis) to speed up demo.

- **AI / Agents**: (Mostly simulated logic)
  - Use of an LLM (Claude) is conceptual; actual code should implement logic explicitly. For example, a "visual analysis agent" could be a function analyzing image metadata. Avoid black-box LLM results without evidence.
  - The agent paradigm is:
    1. **Requirements Parser Agent**: Takes the user’s natural-language input (e.g. “4-chair dental clinic...”) and normalizes it to structured requirements (JSON).
    2. **Property Search Agent**: Filters properties by basics (size, location).
    3. **Vision Agent**: Processes images to detect features (this may be stubbed).
    4. **Analysis Agent**: Combines data to apply rules (calls cost engine, compliance engine).
    5. **Recommendation Agent**: Aggregates results into final output JSON.
  - These "agents" are implemented as modular Python classes/functions in the backend (e.g. in `services/agent_orchestrator.py`).

**Data Flow**:
```
User Input (Next.js) ──> /api/analyze (FastAPI) ──> Parse requirements
                   └─> Fetch properties (CoStar adapter)
                   └─> For each property: 
                        > Fetch Matterport + aerial data
                        > Extract features (rooms, fixtures)
                        > Run cost engine
                        > Run compliance checks
                   └─> Compute scores from criteria
                   └─> Return JSON report
```

## Module Diagram (simplified)
- Frontend (React)
- Backend (FastAPI)
  - routers/ (API endpoints)
  - services/ (analysis logic)
  - providers/ (external adapters)
  - models/ (data schemas)
  - criteria.yaml (scoring config)
  - analysis_results.db (SQLite, optional)
