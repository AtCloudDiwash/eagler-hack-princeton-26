# Turnkey Matchmaker Starter Kit – HackPrinceton Fall 2026

This repository provides the complete Claude Code project starter kit for **Turnkey Matchmaker**. It includes all necessary Markdown specifications, prompts, and configuration files to build a working prototype of the Turnkey Matchmaker system. The goal is to enable an AI agent to help small business owners choose and evaluate commercial spaces by comparing the total cost of opening (including fit-out costs, compliance risks, etc.), not just the listed rent.

Below are the contents of each required file. Copy each section into its respective `.md` file in your project repository. The content is organized to guide Claude (or any developer) through building the system step-by-step.

## CLAUDE.md

This file contains the global, persistent instructions for the Claude Code agent. It sets the overall context and rules for the code generation process.

```
You are "Claude Code," an AI code assistant. Your task is to generate a **complete Turnkey Matchmaker HackPrinceton project** codebase in phases, based on the provided prompts and specifications. Follow these rules precisely:

- **Context**: Turnkey Matchmaker helps small businesses evaluate commercial spaces by comparing total occupancy costs. This is a hackathon project (36 hours) for HackPrinceton Fall 2026.
- **Architecture**: A monorepo with two main parts: a **Frontend** (Next.js + React + TypeScript + Tailwind CSS, optionally using the Shadcn UI library) and a **Backend** (Python + FastAPI + Pydantic + SQLite or SQLModel). The frontend communicates with the backend via versioned REST API endpoints. The backend may have background tasks (e.g. analysis jobs) and a SQLite database for persistence.
- **Data and Integrations**: The system uses multiple data providers:
  - **CoStar API**: commercial real-estate listings (sponsor track data).
  - **Matterport API**: 3D interior property tours.
  - **Vexcel API**: high-resolution aerial imagery of properties.
  - **Geocoding API (optional)**: to map addresses to coordinates.
  - These APIs will be mocked or used with placeholders for API keys. Use environment variables for any real API keys.
- **Compliance Agent**: There must be a separate component (agent) that checks location-specific compliance rules. For example, restaurant health code, zoning parking requirements, ADA accessibility, HVAC/plumbing codes, etc. This agent should use official sources (city/state codes, health department rules) and clearly flag PASS/RISK/UNKNOWN for each rule, with citations if possible.
- **Cost Estimation**: Use a deterministic, rule-based cost engine with configurable cost bands. Do not attempt to use ML for cost prediction. Provide cost ranges, not precise numbers.
- **Configuration-driven Criteria**: Implement a **criteria registry** in YAML or JSON. Each criterion entry includes fields like `id`, `description`, `domain` (e.g. "space", "safety", "regulatory"), `weight`, `hard_block` (bool), `evaluator` (name of function or agent), `required_inputs`, `missing_data_policy`, `evidence_required`, `source`, `thresholds`, and `applicable_jurisdictions`. The system should load criteria dynamically so adding or scaling criteria is a matter of editing the config, not rewriting code.
- **Extensibility**: Ensure adding new criteria or adjusting weights can be done by editing the config file, not by modifying core code. The UI should automatically display any number of criteria from the registry.
- **Prompts**: We will give you a series of "prompt" markdown files (PROMPTS/) instructing you to create or update code. Follow them sequentially.
- **Environment**: Provide instructions for setting up `.env` (copy from `.env.example`), using environment variables, and running the project. List required variables in SECURITY_AND_ENV.md.
- **Testing**: Include a TEST_PLAN.md with unit/integration test strategy. The code should include some tests (e.g. pytest for backend, basic React tests).
- **Demo**: Include a DEMO_RUNBOOK.md that describes how to do a live demo of the working prototype.
- **Code Quality**: Use descriptive names, consistent styling, and comments where helpful. Each file and function should be purposeful. The codebase should be minimal but working.
- **Output**: When executing Claude Code prompts, generate the actual code files as instructed (e.g. use shell commands to create files and write content). Ensure the files compile/run.
- **No Real Secrets**: All secret keys must be in environment variables. Provide a `.env.example` with placeholder names (NEXT_PUBLIC_ for frontend).
- **Focus on MVP**: We have 36 hours. The primary feature is selecting a business type (e.g. a restaurant), entering requirements, then retrieving a small list of properties, evaluating them for fit-out cost and compliance, and outputting a ranked comparison with reasoning. Advanced sponsor features (AWS, LangChain, etc.) are optional and only if they add value.
- **Sponsors and Tech**:
  - **CoStar Group**: Emphasize use of property data and analytics (Matterport/Vexcel integration).
  - **Peri**: Validate with a real small business owner's pain points.
  - **Amazon AWS** (optional): You may deploy backend on AWS or use an AWS AI service (only if needed).
  - **LangChain/AgentForce** (optional): Could be used for orchestrating agents, but not required if complex.
- **Phase Prompts**: Use the PROMPTS markdown files (00-bootstrap.md to 05-demo-polish.md, plus scale-criteria.md) to guide development in phases. Each prompt should be executed in order, with the repository root as working directory.
- **Environment Setup**: Commands provided in prompts assume the root folder is named `turnkey-matchmaker`.
- **Validation**: After each prompt, show expected test output or confirm success (e.g. server starts, sample requests work).
- **Persist State**: After generating code in one prompt, do not delete it in the next prompts; build incrementally.
- **File Structure**: Use a monorepo structure. See README.md for an overview.
- **Documentation**: Each `.md` file describes its area; ensure internal consistency among them.
- **Styling**: Use Tailwind CSS with a dark navy/charcoal theme and teal/cyan accent for the frontend. Use any open-source React component library that fits (like Shadcn UI).
- **Git**: The repository should include a `.gitignore` that excludes node_modules, venvs, `.env`, etc.
- **Limitations**: If an API is not accessible or keys are not provided, create a mock mode (mock data files in `backend/fixtures/`).
- **Execution**: The final deliverable should be the Markdown contents (and code files) themselves, not an explanation.
```

## README.md

The `README.md` provides an overview of the project, how to set it up, and key instructions for developers.

```
# Turnkey Matchmaker

Turnkey Matchmaker is a **HackPrinceton 2026** project that helps small business owners evaluate and choose commercial spaces by comparing the **total cost to open** (rent + renovation + compliance) rather than just monthly rent. The system uses property data from CoStar, 3D tours from Matterport, and aerial imagery from Vexcel to analyze spaces. A compliance agent checks zoning, ADA, and building-code issues for the chosen business type (e.g. restaurant), flagging any risks or requirements.

## Features

- **Property Search & Filtering**: Enter business type and requirements (e.g. "4-chair dental clinic", location, parking needs).
- **Space Analysis**: Retrieve available spaces (using mock CoStar data) and analyze interior (Matterport) and exterior (aerial) features.
- **Fit-out Estimation**: Rule-based engine calculates rough renovation costs (HVAC, plumbing, etc.) and highlights missing infrastructure.
- **Compliance Check**: Automated checks for local regulations (ADA accessibility, zoning parking, restaurant health, etc.) with clear PASS/RISK/UNKNOWN statuses.
- **Ranked Recommendations**: Shows a scorecard comparing total cost-to-open for each property, with cost breakdown and uncertainties.
- **Landlord Request Drafting**: Generates a sample letter to the landlord listing needed improvements and tenant improvement (TI) allowance.

## Tech Stack

- **Frontend**: Next.js (React, TypeScript), Tailwind CSS (dark navy theme with teal/cyan accent), Shadcn UI components.
- **Backend**: Python FastAPI, Pydantic models, SQLite (using SQLModel) for data.
- **Data Providers**: CoStar, Matterport, Vexcel (integrated via APIs or mock data).
- **AI/Agents**: The system uses LLM agents (Claude/Anthropic) to process user input and evidence, but core logic (cost calculations, rule checks) is deterministic.
- **Environment**: Docker optional. `.env` file for API keys.
- **Testing**: Pytest for backend, Jest/React Testing Library for frontend.
- **Deployment**: Can run locally or deployed to AWS (optional).

## Getting Started

1. **Clone the repository** (or generate with Claude Code):
   ```bash
   git clone https://github.com/your-org/turnkey-matchmaker.git
   cd turnkey-matchmaker
   ```
2. **Backend**:
   - Create `backend/.env` from `.env.example` and fill in your API keys.
   - Install dependencies and run the server:
     ```bash
     cd backend
     pip install -r requirements.txt
     uvicorn app.main:app --reload
     ```
   - The backend runs on `http://localhost:8000` with API docs at `/docs`.
3. **Frontend**:
   - Navigate to `frontend` and install dependencies:
     ```bash
     cd frontend
     npm install
     npm run dev
     ```
   - The frontend runs on `http://localhost:3000`.
4. **Using the App**:
   - Open `http://localhost:3000` in your browser.
   - Enter a business profile (e.g. "Open a 40-seat restaurant in Austin, TX, with a kitchen and bathroom requirements").
   - The app will display a comparison of candidate spaces with cost and compliance info.

## Folder Structure

```
turnkey-matchmaker/
├── backend/               # FastAPI backend
│   ├── app/
│   ├── analysis/          # analysis engine modules
│   ├── models/            # Pydantic and SQLModel schemas
│   ├── providers/         # API adapter modules for CoStar, Matterport, Vexcel, etc.
│   ├── services/          # Core business logic (cost engine, compliance checks)
│   ├── main.py            # FastAPI app entrypoint
│   └── ...                
├── frontend/              # Next.js frontend
│   ├── pages/
│   ├── components/
│   ├── public/            # static assets
│   └── ...
├── prompts/               # Claude Code instruction prompts
│   ├── 00-bootstrap.md
│   ├── 01-backend-skeleton.md
│   ├── 02-agent-workflow.md
│   ├── 03-frontend-skeleton.md
│   ├── 04-integrations.md
│   ├── 05-demo-polish.md
│   └── scale-criteria.md
├── .env.example
├── .gitignore
├── criteria.yaml          # initial criteria registry
└── docs/                  # Additional documentation files (see below)
    ├── PROJECT_BRIEF.md
    ├── PRD.md
    ├── ARCHITECTURE.md
    ├── BACKEND.md
    ├── API_CONTRACT.md
    ├── DATA_MODELS.md
    ├── AGENT_ORCHESTRATION.md
    ├── COMPLIANCE_AGENT.md
    ├── COMPLIANCE_RULE_SOURCES.md
    ├── VISION_OVERLAYS.md
    ├── COST_ENGINE.md
    ├── CRITERIA_REGISTRY.md
    ├── FRONTEND_DESIGN.md
    ├── INTEGRATIONS.md
    ├── SECURITY_AND_ENV.md
    ├── SPONSOR_STRATEGY.md
    ├── TEST_PLAN.md
    ├── DEMO_RUNBOOK.md
    ├── BUILD_PLAN.md
    └── DECISIONS_AND_RISKS.md
```

## Authors

- Hackathon Team: [Name1], [Name2], ...
- Claude Code (AI) for code scaffolding and documentation.

## License

Open source for educational purposes. See `LICENSE` for details.
```

## PROJECT_BRIEF.md

This file describes the overall vision and scope in narrative form.

```
# Project Brief – Turnkey Matchmaker

**Objective:** Build an AI-assisted web application that helps entrepreneurs choose commercial real estate by showing the *total cost to open* each space, rather than just rent. This lowers the risk of costly surprises in renovations and compliance issues.

**Users:** First-time or small-business tenants (especially restaurants, clinics, small gyms, etc.) who need to find and evaluate lease spaces. Real estate brokers or property managers could also use it as a decision-support tool.

**Key Problem:** Traditional real estate listings show rent and size, but do not reveal the hidden costs of converting a space. E.g. does the space have restaurant-grade ventilation? Enough plumbing? Suitable parking? Tenants currently spend weeks and money on architects and inspections to answer these questions.

**Proposed Solution:** An AI-driven agent that:
- Takes user requirements (e.g. "4-chair dental clinic in Austin, TX, with lab space and 18 parking spots").
- Pulls candidate properties (from CoStar data).
- Uses 3D tours (Matterport) and aerial images (Vexcel) to **observe** existing features (rooms, plumbing, HVAC, parking).
- Applies rule-based logic to **infer** needed renovations (e.g. install grease hood, add parking spaces) and compliance checks (zoning, ADA, health codes).
- Outputs a **ranked comparison** of spaces, with an estimated build-out cost range, compliance status, and recommended landlord requests.

**Constraints:** 36-hour hackathon. Must deliver a working MVP that convinces judges: a polished UI demo with real-time analysis of at least two properties for a chosen business type (e.g. restaurant). Hardware integration is not required (this is primarily software, leveraging sponsor-provided data). All features should be prototyped with clarity, even if some data is mocked.

**Success Criteria:**
- Judges can interact with the app live, enter a business scenario, and see instant analysis.
- The app clearly shows why a higher-rent space might be cheaper overall.
- Compliance risks and missing information are highlighted.
- The system is robust, with fallbacks (e.g. offline mode if no live API).
- Code quality is good enough for a hackathon; documentation and prompts ensure reproducibility.

```

## PRD.md

This is the Product Requirements Document outlining features, user stories, and acceptance criteria.

```
# Product Requirements – Turnkey Matchmaker

## User Stories

1. **Property Search & Filter**
   - As a user, I can select a business profile (e.g. "restaurant", "dental clinic") and input specific requirements (square footage, number of rooms, parking needed).
   - As a user, I can set my location (city or address).
   - The system shows a list of available properties (mocked CoStar listings) matching basic criteria (size, location, rent range).

2. **Space Analysis**
   - As a user, I can click on a property to analyze it.
   - The system retrieves the property's 3D tour (Matterport) and aerial image.
   - The system extracts visible features (e.g. existing kitchen/bathroom, HVAC units) and measurements (e.g. ADA door widths).

3. **Fit-Out Cost Estimation**
   - As a user, I see a breakdown of required renovations with cost ranges (e.g. "Install commercial kitchen: \$30k–\$50k", "ADA modifications: \$5k–\$8k").
   - The system uses a rule-based cost model (set in criteria) to estimate totals.

4. **Compliance Check**
   - As a user, I see a list of compliance items (e.g. parking requirement, ADA rules, health regulations).
   - Each item is marked PASS, RISK, or UNKNOWN, with a brief explanation (e.g. "RISK: Only 1 restroom visible for a 40-seat restaurant, code requires 2").

5. **Comparison and Ranking**
   - As a user, I can compare multiple properties side-by-side.
   - The app displays a summary card for each: total estimated cost, a composite score, and key pros/cons.
   - Properties are ranked by lowest total cost-to-open (lowest is best).
   - The user can adjust the importance of criteria (weights) via config for testing.

6. **Landlord Request Drafting**
   - As a user, I can generate a sample letter or checklist of items to present to the landlord (e.g. "Please confirm if the rooftop exhaust is rated for a commercial kitchen").

7. **Admin/Configuration**
   - As a developer, I can add or modify scoring criteria (without rewriting code) by editing `criteria.yaml`.
   - As a developer, I can easily add mock data or switch to live APIs via config.

## Non-Functional Requirements

- **Performance**: System should respond within a few seconds for analysis (live demo speed).
- **Usability**: Clean, responsive UI. Dark theme with teal accent.
- **Reliability**: Mock mode works without API keys. Clear error handling.
- **Documentation**: README and technical docs are up-to-date.
- **Extensibility**: Support for adding new business types, new criteria, and sponsor tech.

## Acceptance Criteria

- [ ] Basic Next.js frontend loads without errors.
- [ ] FastAPI backend starts and returns a sample property list at `/api/properties`.
- [ ] Given a sample property (3D image URL & location), the `/api/analyze` endpoint returns a JSON with observed features and cost estimates.
- [ ] The frontend can call `/api/analyze` and display results in a UI card.
- [ ] The compliance checks appear with PASS/RISK flags based on rules in code (e.g. ADA width threshold).
- [ ] The criteria weights can be changed in YAML and affect scoring output.
- [ ] The demo scenario (e.g. comparing 2 restaurant spaces) is fully functional and presentable.
```

## ARCHITECTURE.md

This document outlines the high-level system architecture and module responsibilities.

```
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
```

## BACKEND.md

Detailed design of the backend components, file layout, and main classes.

```
# Backend Design

The backend is built with **Python 3.10+** and **FastAPI**. It exposes versioned REST APIs under `/api/v1/...`. Pydantic is used for request/response models.

### Directory Structure (`backend/`)

- `app/main.py`: Entry point. Sets up FastAPI app, middleware, and includes routers.
- `app/routers/`: Contains API route definitions.
  - `analyze.py`: Endpoint for `/api/v1/analyze` (POST) – analyze a user query.
  - `properties.py`: Endpoint for `/api/v1/properties` (GET) – list/filter properties.
  - `compliance.py`: Endpoint for `/api/v1/compliance` (GET) – (optional) checks compliance for a property.
- `app/models/`: Pydantic/SQLModel definitions.
  - `BusinessProfile.py`: input schema (business type, requirements).
  - `Property.py`: schema for property metadata (location, size, etc.).
  - `AnalysisResult.py`: output schema (scores, costs, compliance flags).
  - `Criterion.py`: schema for scoring criteria.
- `app/providers/`: Adapters to external data.
  - `costar_provider.py`: Stub for CoStar API (returns hard-coded or JSON fixtures).
  - `matterport_provider.py`: Returns sample Matterport links or images.
  - `vexcel_provider.py`: Returns static aerial images or processed data.
  - `geocode_provider.py`: (Optional) Converts address to coordinates.
- `app/services/`: Core logic.
  - `agent_orchestrator.py`: Implements the sequence of analysis steps.
  - `cost_engine.py`: Contains functions to compute cost estimates from identified issues.
  - `compliance_engine.py`: Contains functions to check rules and return PASS/RISK/UNKNOWN.
  - `criteria_manager.py`: Loads and applies criteria weights to generate scores.
  - `utils.py`: Helper functions (e.g. unit conversions, logging).
- `app/analysis/`: Contains any long-running analysis jobs or scripts (if needed).
- `app/config.py`: Reads `criteria.yaml`, environment variables, etc.
- `backend/.env.example`: Example environment file listing all needed keys.
- `backend/requirements.txt`: Python dependencies (FastAPI, Uvicorn, Pydantic, SQLModel, requests, Pillow, etc.)
- `backend/tests/`: Pytest test cases for backend modules.

### API Endpoints (see API_CONTRACT.md)

- **GET** `/api/v1/properties?business=<type>&city=<city>`: Returns candidate properties.
- **POST** `/api/v1/analyze`: Accepts user requirements + selected property IDs; returns analysis report.

### Workflow in Code

1. **BusinessProfile Parsing**: 
   - The backend receives a JSON from the frontend. Validate it using a Pydantic model (`BusinessProfile`). If invalid, return 400.
2. **Fetch Properties**: 
   - Call `costar_provider.search_properties(profile)`. In MVP, this reads from a local JSON fixture or in-memory list and filters by city and size.
3. **Analyze Property**:
   - For each property:
     - Load 3D tour (or static image) via `matterport_provider`.
     - Load aerial image via `vexcel_provider`.
     - Detect visible features (placeholder functions; real image analysis is optional).
     - Run `cost_engine.estimate(...)` with a list of detected missing features.
     - Run `compliance_engine.check(...)` with location and business type.
   - Collect results.
4. **Scoring**:
   - Use `criteria_manager.apply_criteria(profile, properties, analysis_results)`:
     - Load `criteria.yaml` registry.
     - Compute a weighted score for each property.
     - Mark any `hard_block` failures that exclude a property.
5. **Response**:
   - Construct an `AnalysisResult` containing:
     - Observations (rooms, fixtures).
     - Compliance flags.
     - Cost breakdown.
     - Overall score.
     - Any recommended landlord questions.
   - Return JSON to frontend.

### Caching and Mock Mode

- Use `functools.lru_cache` or a simple dict to cache results of expensive calls (e.g., repeated analysis of same property).
- Provide a `--mock` flag or config to force using local sample data. Mock mode uses files in `backend/fixtures/`.
```

## API_CONTRACT.md

This file specifies the REST API endpoints, request parameters, and response formats.

```
# API Contract (v1)

## Base URL
All endpoints are prefixed with `/api/v1`. Example: `http://localhost:8000/api/v1/analyze`.

### 1. GET /api/v1/properties

Retrieve a list of candidate properties for a given business profile.

- **Query Parameters** (all optional, but include at least `city` or `region`):
  - `business_type` (string): The type of business (e.g. "restaurant", "dental_clinic"). Determines which properties are relevant.
  - `city` (string): City name or postal code to filter by location.
  - `min_size` (int, sqft): Minimum square footage.
  - `max_size` (int, sqft): Maximum square footage.
  - `parking` (int): Number of parking spaces required.
  - `budget` (number): Maximum monthly rent (optional).
- **Response**: JSON array of property objects:
  ```json
  [
    {
      "id": "property-123",
      "address": "123 Main St",
      "city": "Austin",
      "state": "TX",
      "zip": "78701",
      "size_sqft": 2500,
      "rent": 5000,
      "image_url": "https://.../thumbnail.jpg"
    },
    {
      "id": "property-456",
      "address": "456 Elm St",
      "city": "Austin",
      "state": "TX",
      "zip": "78702",
      "size_sqft": 2400,
      "rent": 4800,
      "image_url": "https://.../thumb2.jpg"
    }
  ]
  ```

### 2. POST /api/v1/analyze

Analyze one or more selected properties for fit-out and compliance.

- **Request Body** (JSON):
  ```json
  {
    "business_profile": {
      "type": "restaurant",
      "details": "40 seats, kitchen needed, 2 bathrooms required, 20 parking spaces",
      "city": "Austin",
      "state": "TX"
    },
    "property_ids": ["property-123", "property-456"]
  }
  ```
- **Response**: JSON object containing analysis results:
  ```json
  {
    "business_type": "restaurant",
    "results": [
      {
        "property_id": "property-123",
        "score": 82.5,
        "total_cost_estimate": {"min": 300000, "max": 350000},
        "breakdown": {
          "kitchen_install": {"min": 50000, "max": 80000},
          "hvac_upgrade": {"min": 20000, "max": 30000},
          "plumbing": {"min": 10000, "max": 15000},
          "other": {"min": 5000, "max": 10000}
        },
        "compliance": {
          "ADA_accessible": {"status": "PASS", "notes": "Door width 36in meets ADA"},
          "parking_requirement": {"status": "RISK", "notes": "Only 15 spaces visible, 20 required by zoning"},
          "health_department": {"status": "UNKNOWN", "notes": "Health permit not on file"},
          ...
        },
        "questions_for_landlord": [
          "Is the rooftop HVAC rated for restaurant kitchen exhaust?",
          "How many parking spaces are officially assigned to this unit?"
        ]
      },
      {
        "property_id": "property-456",
        ...
      }
    ]
  }
  ```
- **Fields Explained**:
  - `score`: Composite score (0-100) based on criteria (higher is better).
  - `total_cost_estimate`: Estimated range to build out the space.
  - `breakdown`: Cost components by category.
  - `compliance`: Each rule with status (`PASS`/`RISK`/`UNKNOWN`) and explanation.
  - `questions_for_landlord`: Concise questions to clarify unknowns or negotiate TI allowances.
```

## DATA_MODELS.md

Describe the core data schemas (Pydantic/SQLModel models) used in the backend.

```
# Data Models

These models define the structure of data in requests, responses, and storage.

## app/models/BusinessProfile.py

- **BusinessProfile** (Pydantic BaseModel):
  - `type: str` – Business category (e.g. "restaurant", "gym", "clinic").
  - `details: str` – Free-text describing requirements (parsed into structured needs).
  - `city: str`
  - `state: str`

*Example:*
```python
class BusinessProfile(BaseModel):
    type: str
    details: str
    city: str
    state: str
```

## app/models/Property.py

- **Property** (SQLModel or Pydantic):
  - `id: str`
  - `address: str`
  - `city: str`
  - `state: str`
  - `zip: str`
  - `size_sqft: int`
  - `rent: float` (monthly)
  - `latitude: float` (optional)
  - `longitude: float` (optional)
  - `image_url: str` (thumbnail)
  - `matterport_url: str` (link to 3D tour)
  - `available: bool`

*Example:*
```python
class Property(BaseModel):
    id: str
    address: str
    city: str
    state: str
    zip: str
    size_sqft: int
    rent: float
    latitude: Optional[float]
    longitude: Optional[float]
    image_url: Optional[str]
    matterport_url: Optional[str]
```

## app/models/AnalysisResult.py

- **AnalysisResult** (Pydantic):
  - `property_id: str`
  - `score: float`
  - `total_cost_estimate: {min: float, max: float}`
  - `breakdown: Dict[str, {min: float, max: float}]` (cost categories)
  - `compliance: Dict[str, {status: str, notes: str}]`
  - `questions_for_landlord: List[str]`

*Example:*
```python
class AnalysisResult(BaseModel):
    property_id: str
    score: float
    total_cost_estimate: CostRange
    breakdown: Dict[str, CostRange]
    compliance: Dict[str, ComplianceStatus]
    questions_for_landlord: List[str]
```

- **CostRange**: model with `min: float`, `max: float`.
- **ComplianceStatus**: model with `status: str` (PASS/RISK/UNKNOWN), `notes: str`.

## app/models/Criterion.py

- **Criterion** (for criteria registry, if loaded as model):
  - `id: str`
  - `description: str`
  - `domain: str`
  - `weight: float`
  - `hard_block: bool`
  - `evaluator: str`
  - `required_inputs: List[str]`
  - `missing_data_policy: str`
  - `evidence_required: bool`
  - `source: str`
  - `thresholds: any` (dependent on evaluator)
  - `jurisdictions: List[str]`

*Example YAML (criteria.yaml) entry:*
```yaml
- id: 'adequate_parking'
  description: 'Parking meets local zoning requirements'
  domain: 'regulatory'
  weight: 10
  hard_block: false
  evaluator: 'parking_checker'
  required_inputs: ['visible_parking_count', 'business_parking_req']
  missing_data_policy: 'assume_risk'
  evidence_required: true
  source: 'City of Austin Zoning Code'
  thresholds:
    min_spaces_per_sqft: 0.001
  jurisdictions: ['TX', 'Austin']
```

## Relationships

- A `BusinessProfile` leads to multiple `AnalysisResult`s (one per property).
- Criteria are independent of specific data models and are loaded from `criteria.yaml` at startup.
```

## AGENT_ORCHESTRATION.md

This doc explains how the analysis workflow (“agents”) is organized.

```
# Agent Orchestration

We conceptualize the backend logic as a sequence of "agents" or steps. Each step processes data and passes it on.

1. **Requirements Parser Agent**
   - Input: `BusinessProfile` (free-form details).
   - Action: Use simple NLP heuristics or regex to extract structured needs:
     - Number of seats/rooms (look for digits, e.g. "40-seat").
     - Special needs: "kitchen", "plumbing", "parking 20".
     - Output: A structured dict, e.g. `{"type": "restaurant", "seats": 40, "bathrooms": 2, "parking": 20}`.
   - (For MVP, manual parsing rules are fine. No external LLM calls.)

2. **Property Search Agent**
   - Input: Parsed requirements and location (city, state).
   - Action: Call `costar_provider.search_properties(location, size_range, type)`.
   - Filter results by suitability (minimum size, user budget, etc.).
   - Output: List of `Property` records.

3. **Vision Agent**
   - Input: A `Property` record.
   - Action: 
     - Retrieve data from `matterport_provider` (3D tour or static floor plan image).
     - Retrieve data from `vexcel_provider` (aerial image).
     - (Optional: Run simple object detection on images if feasible; otherwise use placeholders.)
     - Determine observable features: count of bathrooms, visible kitchen equipment, HVAC units, parking count.
   - Output: An `observations` dict for the property, e.g. `{"bathrooms_visible": 1, "kitchen_equipment": false, "parking_visible": 15}`.

4. **Analysis Agent**
   - Input: Observations, user requirements, property metadata.
   - Action:
     - **Fit-Out Identification**: Compare user needs vs observations to find gaps:
       - If kitchen required but none visible, mark "needs_kitchen_install".
       - If bathrooms needed > visible, mark "needs_bathroom_add".
       - If visible parking < required, mark "needs_extra_parking".
     - **Cost Engine**: For each identified gap, estimate cost range (see COST_ENGINE.md).
     - **Compliance Engine**: Check each relevant rule (see COMPLIANCE_AGENT.md).
       - Example: ADA door width from Matterport measurements.
       - Example: Zoning parking from user location.
     - Prepare partial result: list of missing features and compliance results.
   - Output: Intermediate results to feed scoring.

5. **Recommendation Agent**
   - Input: Analysis results from above for each property.
   - Action:
     - Load scoring criteria from `criteria.yaml`.
     - Compute weighted scores (lower cost, PASS flags increase score; RISK flags decrease).
     - Normalize to a 0-100 scale.
     - Identify any `hard_block` failures (e.g. if `hard_block` flag is triggered, mark property as not recommended).
     - Format final JSON output (see API_CONTRACT.md).
   - Output: Final analysis report (list of `AnalysisResult` for each property).

All these steps happen inside the `/api/v1/analyze` handler. For performance, you may parallelize analysis of multiple properties (using threads or asyncio). Use clear function boundaries: e.g., implement each agent as a class or function with well-defined inputs/outputs.

```

## COMPLIANCE_AGENT.md

Details on the compliance-checking component.

```
# Compliance Agent

The compliance agent evaluates whether a candidate space meets location-specific requirements. It should not certify legality but flag potential issues.

### Categories of Compliance Checks

1. **Zoning and Permits**
   - *Example:* Parking requirements per zoning. (Tx zoning code might specify X parking spaces per square foot for restaurants.)
   - *Example:* Land use: Is the property zoned for commercial use or specifically for restaurants, medical clinics, etc.?
   - Data Source: City/county zoning maps or CoStar listing data (use `property.zoning` field if available).
   - Output Status: `PASS` if meets known criteria, `RISK` if not, `UNKNOWN` if data is missing.

2. **ADA Accessibility**
   - *Example:* Door widths, number of accessible restrooms, wheelchair ramp presence.
   - Data Source: Matterport measurements (if possible, measure door frames and areas).
   - Threshold: ADA typically requires 32–36 inch clear door width.
   - Output: `PASS` if measured width >= 32in, `RISK` if <32in or no data.

3. **Health and Safety (for restaurants)**
   - *Example:* Is a grease trap present? Is there a permit on file?
   - Data Source: Likely unavailable in imagery; skip or set `UNKNOWN`.
   - We may skip detailed health code; instead, focus on obvious needs (kitchen exhaust existence).
   - Output: `UNKNOWN` with note "Requires inspection."

4. **Building Codes**
   - *Example:* Maximum occupancy vs floor area (not required for early stage).
   - *Example:* Existing HVAC capacity vs expected load.
   - Data Source: Rooftop unit size from aerial (if labeled), or skip.
   - Output: Usually `UNKNOWN` or simple check if feasible.

5. **Plumbing/Electrical Capacity**
   - *Example:* Number of visible sinks, restrooms (from interior plan).
   - Data Source: Matterport snapshot labeling.
   - Output: `PASS`/`RISK` if noticeably insufficient.

### Jurisdiction-Specific Rules

- Use the property city/state to narrow checks. For Hackathon MVP, implement one city’s known rules (e.g. Austin, TX:
  - Parking: 1 space per 75 sqft (or refer to zoning code).
  - ADA: state follows federal ADA.
  - Health: Restaurants need grease trap and ventilation (Flag if none visible).

- Provide citations in `COMPLIANCE_RULE_SOURCES.md` for each rule used.

### Implementation Notes

- The compliance agent runs on each property analysis. It should be a pure function: `def check_compliance(property, business_profile) -> Dict[str, (status, notes)]`.
- Mark a rule as `RISK` if the property clearly violates (e.g. fewer parking than threshold).
- Mark as `UNKNOWN` if we cannot determine (e.g. cannot see electrical panel).
- Never assert compliance with absolute certainty, always allow human follow-up.
- The output `status` values are `PASS`, `RISK`, or `UNKNOWN`.
- In the final report UI, RISK items should be highlighted in red/orange, PASS in green, UNKNOWN in gray.
```

## COMPLIANCE_RULE_SOURCES.md

List the official sources for compliance rules. These should be real or example citations.

```
# Compliance Rule Sources

This document lists references for the rules used by the Compliance Agent.

1. **ADA Standards**:
   - U.S. Dept. of Justice: *2010 ADA Standards for Accessible Design*. Section 404 (Doors and Entrances). See e.g. https://www.ada.gov/regs2010/2010ADAStandards/2010ADAStandards_prt.pdf.

2. **Zoning Requirements (Austin, TX)**:
   - City of Austin Zoning Code: *Commercial Parking Requirements*. (Example: 1 space per 75 sqft for restaurants). [Provide link to city code PDF or website, e.g. Austin Land Development Code.]
   - City of Austin: *Land Use, Commercial*. (Verifies restaurant is allowed in the zone).

3. **Health Code (Texas)**:
   - Texas Food Establishment Rules (TFER). Section on grease traps and ventilation. [https://texreg.sos.state.tx.us/…].
   - Note: For MVP, we mention that kitchens require ventilation per TFER Section X.

4. **International Plumbing Code (IPC)**:
   - Tables for number of fixtures per occupant. (We could derive bathroom requirements from occupancy).
   - [e.g. IPC 2021, Appendix C].

5. **Other**:
   - Americans with Disabilities Act (federal standard): https://www.ada.gov.
   - Local building code references (if any found for demo city).

**Disclaimer**: These rules are for informational use only. The app does NOT replace a licensed inspector or architect. If a check is `UNKNOWN`, it advises the user to verify with a professional.

```

## VISION_OVERLAYS.md

Guidelines for image processing and overlay presentation.

```
# Vision and Image Overlays

The app will present aerial and interior images with annotations to explain findings.

## Aerial Images (Vexcel)

- Display the aerial image in the frontend with **normalized coordinate overlays** highlighting relevant features:
  - **Rooftop HVAC units**: Mark bounding boxes over identified HVAC on roof.
  - **Parking areas**: Shade or outline parking lot and count visible spaces.
  - **Ingress/Egress**: Highlight curb cuts or entry points.
- Implementation:
  - If Vexcel API provides metadata (e.g. building outlines or parking polygons), use that to draw shapes.
  - Otherwise, use a placeholder annotation layer (e.g. HTML `<div>`s with absolute positioning).
  - Normalize coordinates so overlays scale with image size.
- UI: Overlay boxes in teal color with semi-transparent fill. Tooltip on hover to show notes (e.g. "3 HVAC units detected").

## Interior Images (Matterport)

- Ideally embed a Matterport 3D viewer component (if licensing allows). If not, use a static floorplan screenshot:
  - On the image, draw markers/icons for:
    - **Plumbing fixtures** (sinks, toilets).
    - **Electric panels**.
    - **Doors** (mark width arrows for ADA).
  - Alternatively, list detected items next to image with icons.
- Implementation:
  - Use Matterport SDK if available (requires API key). As fallback, show a static image and use CSS overlays for measurements.
  - Show dimension lines for any ADA corridors (if coordinate data is available).
  - Example: A green arrow icon for a 36in door.
- UI: Use SVG or Canvas overlays for measurements. If not feasible, at least list observations next to image.

## Visual Evidence in Report

- Each compliance/cost finding in the UI should reference the image when possible:
  - "ADA Accessible: PASS (36in door width) [image]" where [image] is clickable.
  - "Visible plumbing: 2 sinks, 1 toilet" with icon.

Remember: Any visual detection is best-effort. Default to text if unsure. The overlay is meant to **illustrate**, not to be a formal blueprint.

```

## COST_ENGINE.md

Explain how renovation costs are estimated.

```
# Cost Estimation Engine

This module computes rough cost ranges for required renovations and improvements. It is **deterministic and rule-based**. Do not attempt to use ML or precise calculations; use broad estimates and clearly state assumptions.

### Cost Factors

For each type of work, we will define a **cost-per-unit** or a flat range. Examples:
- **Kitchen Installation** (if none exists):
  - Base cost per kitchen: \$40,000 – \$60,000 for a small restaurant kitchen (hood, vent, basic fixtures).
- **HVAC Upgrade**:
  - Cost per rooftop unit: \$15,000 – \$25,000 each (depending on capacity).
- **ADA Improvements**:
  - Ramp installation: \$5,000 – \$10,000.
  - Door widening: \$1,000 – \$3,000 per door.
- **Plumbing**:
  - Per new bathroom (toilet + sink): \$10,000 – \$15,000.
  - For a dental clinic, cost per treatment room plumbing: \$5,000 – \$8,000.
- **Electrical Upgrade**:
  - Per panel: \$8,000 – \$12,000.
- **Other**:
  - Demolition/Construction Labor: estimate 10–20% of total build-out.
  - Permits/Fees: flat \$5,000–\$10,000.

### Strategy

1. Identify missing infrastructure from analysis (e.g., "needs 1 kitchen", "needs 5 parking spaces").
2. For each missing item, assign a cost range by looking it up:
   - We can hardcode cost ranges in the code or load from a small JSON (`costs.json`).
   - Adjust based on size: e.g. larger square footage or more seats might mean a bigger kitchen.
3. Sum all min and max costs to produce `total_cost_estimate`.
4. Apply a margin (e.g. +20%) to account for contingency if desired.

### Example

```python
def estimate_cost(missing_items: List[str], business_type: str) -> CostRange:
    # Example pseudocode
    total_min = 0
    total_max = 0
    for item in missing_items:
        if item == "kitchen_install":
            total_min += 40000
            total_max += 60000
        elif item == "bathroom_add":
            total_min += 10000
            total_max += 15000
        elif item == "extra_parking":
            # Suppose cost per space is high (land cost not included)
            total_min += 5000 * num_extra_spaces
            total_max += 8000 * num_extra_spaces
        # ... other items ...
    return {"min": total_min, "max": total_max}
```

### Documentation

- Document all cost assumptions (see COMMENT in code and in this doc).
- Clearly label cost results as **estimates** and not quotes.
- The frontend should present costs as a range and note the assumptions (e.g. "Costs are preliminary estimates; actual construction quotes may vary.").

```

## CRITERIA_REGISTRY.md

Specification of the dynamic criteria registry.

```
# Criteria Registry

We use a YAML (or JSON) file (`criteria.yaml`) to define scoring criteria. This makes the system extensible: adding or adjusting criteria is done by editing this config, not code.

## Structure of `criteria.yaml`

Each entry in the YAML list is a criterion with fields:

- `id` (string): unique key.
- `description` (string): human-readable description.
- `domain` (string): e.g. "space", "regulatory", "cost".
- `weight` (float): how important this criterion is relative to others.
- `hard_block` (bool): if true, failing this criterion means the space is disqualified.
- `evaluator` (string): name of the function or rule that evaluates this criterion.
- `required_inputs` (list of str): pieces of data needed from analysis, e.g. `["visible_parking", "required_parking"]`.
- `missing_data_policy` (string): policy if data is missing (`"assume_risk"`, `"ignore"`, etc.).
- `evidence_required` (bool): whether this criterion needs observable evidence to score positively.
- `source` (string): reference to code or rule source (for display/citation).
- `thresholds`: criterion-specific thresholds.
- `applicable_jurisdictions` (list of str): regions where this rule applies (use "*ALL*" for general).

### Example Criteria Entries

```yaml
- id: "parking_sufficiency"
  description: "Enough parking spaces for the business type"
  domain: "regulatory"
  weight: 10
  hard_block: false
  evaluator: "check_parking_spaces"
  required_inputs:
    - "visible_parking_count"
    - "business_parking_requirement"
  missing_data_policy: "assume_risk"
  evidence_required: true
  source: "City of Austin Zoning Code, Sec. 25-6-478"
  thresholds:
    min_ratio: 1  # 1 parking spot per 20 seats
  applicable_jurisdictions: ["ALL"]

- id: "ada_door_width"
  description: "Doorway meets ADA width requirements"
  domain: "safety"
  weight: 5
  hard_block: false
  evaluator: "check_ada_door_width"
  required_inputs: ["door_width_in_inches"]
  missing_data_policy: "assume_risk"
  evidence_required: true
  source: "ADA Title III, 2010 Standards"
  thresholds:
    min_width: 32
  applicable_jurisdictions: ["ALL"]

- id: "kitchen_presence"
  description: "Existing commercial kitchen equipment"
  domain: "space"
  weight: 15
  hard_block: false
  evaluator: "check_kitchen_equipment"
  required_inputs: ["kitchen_equipment_visible"]
  missing_data_policy: "assume_cost"
  evidence_required: false
  source: "Restaurant Fit-Out Requirements"
  thresholds: {}
  applicable_jurisdictions: ["ALL"]
```

## How the Registry is Used

- On startup, the backend loads `criteria.yaml`.
- Each criterion's `evaluator` corresponds to a function in `criteria_manager.py` that returns a score or boolean.
- The `weight` influences how much each criterion contributes to the final score.
- The system iterates through criteria, and if `hard_block` and condition is failed, the property gets disqualified or drastically reduced.
- The frontend can display each criterion (ID and description) in a comparison table.

## Scaling Criteria

- To **add a new criterion**, simply append to `criteria.yaml`. Provide an evaluator name and implement the corresponding function.
- Example: To add "window_line_of_sight" criterion, create an entry with an `evaluator` and update `criteria_manager.py`.
- The UI should automatically render any criteria listed here.

```

## FRONTEND_DESIGN.md

UI/UX design notes for the Next.js frontend.

```
# Frontend Design

The frontend is a modern, responsive web app. Key pages/components:

1. **Home / Input Page**:
   - Header with app title/logo ("Turnkey Matchmaker").
   - Form for **Business Profile**:
     - Dropdown for business type (restaurant, clinic, gym).
     - Text input for details (placeholder: "e.g. 4-chair dental clinic in Austin, TX...").
     - Location inputs (City, State or zip).
     - Submit button ("Find Spaces").
   - Dark navy background, with teal/cyan accent on buttons and highlights.

2. **Property Selection Page**:
   - After submitting profile, display a grid or list of property cards (from `/properties`).
   - Each card: thumbnail image, address, key stats (size, rent).
   - Checkbox or "Analyze" button to select one or more properties.
   - "Compare" button to run analysis on selected ones.

3. **Analysis Report Page**:
   - Layout: Side-by-side cards or a table for each property.
   - **Summary Card** (top of each): shows total cost range, overall score, key highlight (e.g. "High HVAC cost").
   - **Breakdown Section**: Expandable section listing:
     - Renovation cost breakdown (list or bar chart).
     - Compliance results table: columns for rule, status (PASS/RISK), note.
   - **Overlays Section**: Interactive images:
     - Aerial image with overlays (CVs).
     - Optional Matterport embedded viewer or static floorplan.
   - **Landlord Request**: Text area with bullet points of questions for landlord.
   - Visual style: Use Tailwind CSS (dark background, white text). Use icons (from Heroicons or similar) for items like kitchen, parking, checkmark, warning.

4. **Navigation**:
   - Navbar with "Home", "Settings" (criteria weights, optional admin).
   - "Back" button on Analysis to return to property list.

### Component Breakdown

- `BusinessProfileForm`: Collects input.
- `PropertyCard`: Shows property info on selection page.
- `AnalysisCard`: Displays analysis for one property.
- `CriteriaTable`: Dynamic table of criteria vs. properties.
- `MapOverlay` / `ImageOverlay`: Component to overlay annotations on images.
- `LandlordLetter`: Generates and shows textarea with items.

### Responsive Design

- Mobile: Cards stack vertically.
- Desktop: Use grid or flex for side-by-side.
- Use Tailwind utility classes; avoid heavy custom CSS.

### Theming

- Dark theme: `bg-slate-900`, text `text-white`.
- Accent: `text-cyan-400` or `bg-cyan-500`.
- Use [`@tailwindcss/forms`](https://github.com/tailwindlabs/tailwindcss-forms) for nice form elements.
- If using Shadcn/UI, integrate minimal components for dialogs or tabs.

### Visual Consistency

- Use a consistent card style (rounded corners, shadow).
- Align icons and text in lists.
- Provide tooltips for compliance status using small `?` icon.

```

## INTEGRATIONS.md

Description of external integrations and how to handle them.

```
# Integrations

We integrate with the following external data services. For hackathon, we'll use mock data or simple HTTP calls if possible.

## CoStar API (Property Listings)

- **Purpose**: Fetch property metadata (address, size, rent, location).
- **Integration**:
  - If CoStar provides a trial API or dataset, use it. Otherwise, include a JSON fixture (`fixtures/properties.json`) with sample listings.
  - The backend's `costar_provider.py` should abstract the API. For now:
    - Implement a function `search_properties(business_profile)` that reads from `fixtures/properties.json` and filters by city/state and size.
    - If an actual CoStar endpoint exists, use `requests` to call it with `COSTAR_API_KEY` from `.env`.
- **Data Fields**: ID, address, city, state, zip, size, rent, geocoordinates (if available), Matterport tour URL.

## Matterport API (3D Interior Tours)

- **Purpose**: Get a 3D model or snapshot of the property's interior.
- **Integration**:
  - Use Matterport SDK or API if you have a key (`MATTERPORT_API_KEY`). For MVP, we can embed a public demo mattertag or use a static image link.
  - Create `matterport_provider.get_interior(property_id)` that returns an object with:
    - `floor_plan_image_url` (static PNG or JPG of floor plan).
    - `matterport_embed_url` (for iFrame embed) or `None`.
    - Any metadata if available (e.g. list of rooms).
  - If no real API, store a couple of example images in `backend/static/` and map property IDs to them.

## Vexcel Imaging (Aerial Imagery)

- **Purpose**: High-resolution overhead images of properties.
- **Integration**:
  - If Vexcel has an API (`VEXCEL_API_KEY`), use it to fetch an image by coordinates.
  - Alternatively, use a public satellite image API (e.g. Mapbox or Google Static Maps as fallback).
  - `vexcel_provider.get_aerial(property)` should return:
    - `image_url` or binary data of aerial.
    - Optionally, annotation data (GPS polygons).
  - For MVP, include sample aerial images in `backend/static/aerials/`.
  
## Geocoding API (Optional)

- To convert an address to lat/long for aerial fetch.
- Could use Google Geocoding or a free API (e.g. OpenStreetMap Nominatim).
- Define `providers/geocode.py` with function `geocode(address)` that returns lat/lng.
- Use `GEOCODING_API_KEY` if needed.

## Offline/Mock Mode

- If any API fails or `.env` keys are missing, fall back to local data:
  - Use flag `USE_MOCK_DATA` or check if keys are empty.
  - The frontend should still work with mock results (`results.json`).

## API Keys and Configuration

- All keys are read from environment variables (see SECURITY_AND_ENV.md).
- The code should handle missing keys gracefully by switching to mock.

```

## SECURITY_AND_ENV.md

Instructions on environment variables and security considerations.

```
# Security and Environment Configuration

### .env Files

- Create a `.env` file in the `backend/` directory by copying `.env.example`.
- Example content of `.env.example`:
  ```
  COSTAR_API_KEY=your_costar_key_here
  MATTERPORT_API_KEY=your_matterport_key_here
  VEXCEL_API_KEY=your_vexcel_key_here
  GEOCODING_API_KEY=your_geocoding_key_here
  ANTHROPIC_API_KEY=your_anthropic_key_here
  ```

- The frontend Next.js app should not contain real secret keys. Only put non-sensitive configs in `NEXT_PUBLIC_` variables if needed. (E.g., `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` if used for a map tile.)
- Add `.env` and any private key files to `.gitignore`. Only commit `.env.example` with placeholders.

### API Keys

- **CoStar**: If you have developer access, store the API key in `COSTAR_API_KEY`. Otherwise, leave blank to use mocks.
- **Matterport**: `MATTERPORT_API_KEY` for embedding (if required). For static images, may not need it.
- **Vexcel Imaging**: `VEXCEL_API_KEY` if using their API.
- **Geocoding**: `GEOCODING_API_KEY` (e.g. Google or Mapbox) if performing live geocode.
- **Anthropic (Claude)**: `ANTHROPIC_API_KEY` if using Claude for any NLP. (This project uses rules, so this may not be needed.)

### Security Practices

- Do not print secrets in logs.
- Use HTTPS endpoints for all API calls.
- CORS: Allow frontend `localhost:3000` to call backend `localhost:8000`.
- Rate-limit calls in the backend if looping over many properties (to avoid accidental DDoS).
- For demo, consider disabling any unsafe operations and use safe defaults.

### Running in Live vs Mock

- By default, the app should run in "mock mode" if keys are missing.
- If `ENV=production` or keys are present, it should attempt real API calls.
- Provide clear console logs about which mode is active.

```

## SPONSOR_STRATEGY.md

How this project aligns with sponsor tracks and where to highlight sponsor tech.

```
# Sponsor Strategy

Focus on the following sponsors/prizes:

- **CoStar Group (Commercial Real Estate Data)**
  - *Fit:* We directly use CoStar data and related property analytics (Matterport and Vexcel).
  - *Action:* Highlight the use of CoStar's market data (even if mocked) and analytics from Matterport/Vexcel.
  - *Prize:* Emphasize solving CoStar’s challenge by combining multi-source property data. Mention CoStar integration in marketing blurb.
  - *Tech:* If possible, use any CoStar-provided sample dataset or API (with sponsor permission) instead of generic data.

- **Peri (Forward Deployed Challenges)**
  - *Fit:* Show we talked to a real small business owner (restaurant or clinic) and included their feedback.
  - *Action:* Include a comment or slide in pitch: “We validated with [Name, Role] from [Business] who said *‘The worst surprise was that …’* and coded for that exact problem.”
  - *Prize:* Document the interview notes in our design (maybe as an appendix or comment).

- **Amazon (AWS, AI services)**
  - *Fit:* AWS for hosting or AI.
  - *Action:* If time allows, deploy the backend on AWS (Elastic Beanstalk or EC2) or use AWS Lambda for microservices.
  - *Optional:* Use AWS Textract or Rekognition for any image analysis (though not needed for MVP).
  - *Prize:* Mention AWS credits for hosting and using AWS for reliability.

- **Scale AI, LangChain, Agent Platforms**
  - *Fit:* Potential use of LLM orchestration or datasets.
  - *Action:* If we integrate Claude/Anthropic via API, note it. Use LangChain to structure agent flow if comfortable.
  - *Note:* Keep it simple; do not overshoot scope.

- **Photon, arlq, ChatOverflow, Projects Board, Justin Bojarski**
  - *Fit:* These sponsors are more community/prizes. Not specific tech requirements.
  - *Action:* In Devpost or pitch, acknowledge Princeton CS and general idea value.
  
**Key Point:** Emphasize *unique multi-layer analysis using sponsor data.* In demo and presentation, cite that we are solving a "CoStar challenge" by combining building data, 3D tours, and zoning rules into one agent.

```

## TEST_PLAN.md

Outline of the testing strategy.

```
# Test Plan

We will implement tests to ensure core functionality works. Focus on:

## Backend (Pytest)

- **Smoke Tests**:
  - Run `uvicorn app.main:app` and verify `/health` or root returns 200.
  - Check `/api/v1/properties` returns JSON (with mock data).
  - Check `/api/v1/analyze` accepts sample input and returns correct structure.

- **Unit Tests (in `backend/tests/`)**:
  - `test_cost_engine.py`: Test cost calculations for known scenarios (e.g. if missing kitchen, returns expected cost range).
  - `test_compliance_engine.py`: Test compliance logic with mocked inputs (e.g. door width values, parking counts).
  - `test_criteria_manager.py`: Test scoring using a small custom criteria file.
  - `test_providers.py`: If using mock providers, ensure they return expected fixtures.

- **Integration Test**:
  - Simulate a full flow: call `/api/v1/properties` then `/api/v1/analyze` with one property. Validate overall JSON shape and status codes.

- **Error Cases**:
  - Missing env keys => mock mode: test that properties endpoint still works.
  - Invalid input to `/analyze` returns 400.

## Frontend (Jest/React Testing Library)

- **Smoke Test**:
  - Render main components (`BusinessProfileForm`, `PropertyCard`, `AnalysisCard`) with minimal props to ensure no crash.

- **Component Tests**:
  - `BusinessProfileForm`: simulate user input and verify it updates state.
  - `PropertyCard`: render with sample data and check text.
  - `AnalysisCard`: render with a dummy `AnalysisResult` and check that cost and compliance appear.

- **API Integration**:
  - Use a mock service worker or Jest mocks to simulate API responses.
  - Test that submitting the form triggers a fetch and that the results page displays returned data.

## Manual Testing

- **Default Demo**:
  - Pre-load a demo scenario: e.g. two sample restaurants.
  - Verify all UI interactions manually:
    - Profile input -> property list -> select -> compare.
    - Check overlays appear.
    - Check criteria weighting.

- **Edge Cases**:
  - No properties found message.
  - Partial data (e.g. missing Matterport image) path.

## Testing Environment

- Add `scripts` in `package.json` and `Makefile`:
  - `npm test` for frontend.
  - `pytest` for backend.
- Ensure CI (if used) runs both suites.
```

## DEMO_RUNBOOK.md

Step-by-step instructions for the live demo.

```
# Demo Runbook

This guide explains how to present the working prototype in a live demo.

1. **Setup Check (before demo)**:
   - Confirm frontend (`localhost:3000`) and backend (`localhost:8000`) are running. No errors in console.
   - Ensure the `.env` (or mock mode) is set so the app has at least 2 sample properties to compare.
   - Pre-select a demo business profile and sample properties (know which properties by name).
   - Run a quick test call to `/api/v1/analyze` to warm caches.

2. **Introduction (0:00-0:15)**:
   - Briefly introduce the problem: “Traditional CRE search only shows rent, hiding the real cost.”
   - State the solution: “Turnkey Matchmaker shows the actual cost to open a business in each space.”

3. **Show Home Page (0:15-0:45)**:
   - Enter a scenario: e.g., “40-seat restaurant in [Demo City] requiring a kitchen and 2 bathrooms.”
   - Click “Find Spaces”.

4. **Property Selection (0:45-1:00)**:
   - Show the list of candidate spaces (2 or 3).
   - Highlight addresses and monthly rent.
   - Select two spaces for comparison.

5. **Analysis (1:00-1:30)**:
   - Click “Compare”.
   - Point out the loading spinner (if any) and explain it’s running analysis.

6. **Review Results (1:30-2:30)**:
   - For **Property A**: show total cost range (\$X–\$Y), score, key findings.
   - Expand breakdown: highlight that it needed a kitchen + ADA fixes, so higher cost.
   - Show overlays: roof HVAC units highlighted, door width noted.
   - For **Property B**: cheaper total cost because it already had a kitchen.
   - Emphasize surprising insight: “Even though A’s rent is lower, B is \$Z cheaper overall due to fewer renovations.”

7. **Compliance Flags**:
   - Scroll to compliance section.
   - Show one `RISK` (e.g. parking shortfall) with note “Only 15 of required 20 spaces”.
   - Show a `PASS` (e.g. ADA door width).

8. **Landlord Requests**:
   - Reveal the draft list of landlord questions (e.g. about exhaust capacity, assigned parking).
   - Mention this helps negotiate TI allowances.

9. **Custom Weighting (optional)**:
   - If time, go to Settings or developer console, adjust a criterion weight (like Parking weight).
   - Rerun scoring and show how ranking changes.

10. **Conclusion (2:30-2:50)**:
    - Summarize: “This demo showed how Turnkey Matchmaker helps avoid hidden costs using real data.”
    - If applicable, mention sponsors: “We used CoStar/Matterport/Vexcel data per sponsor requirements.”

11. **Fallback Plan**:
    - If something fails, be ready with screenshots or a recorded video of the above steps.
    - Emphasize the core functionality even if some integrations are offline.

12. **Q&A Prep**:
    - Be prepared to explain where the data came from, any assumptions made, and how adding more data (like actual CoStar API) would enhance it.
```

## BUILD_PLAN.md

Rough breakdown of tasks and timeline for 36 hours.

```
# Build Plan (36 Hours)

We have 36 hours (including setup and demo). Here’s a tentative timeline:

- **Hour 0-1**: Project setup
  - Run `00-bootstrap` prompt to scaffold the repo, install frameworks.
  - Verify local environment.

- **Hour 1-4**: Backend skeleton
  - Implement basic FastAPI app with `/health`.
  - Create models and endpoints (prompt `01-backend-skeleton`).
  - Write minimal providers that return mock properties.
  - Test GET `/properties` returns sample list.

- **Hour 4-8**: Agent orchestration, cost & compliance logic
  - Implement `agent_orchestrator` and cost/compliance modules.
  - Load criteria from `criteria.yaml`.
  - Test analysis on hardcoded example.
  - Add Pytest unit tests for cost and compliance (create initial tests).

- **Hour 8-12**: Frontend skeleton
  - Use `create-next-app` or similar.
  - Build `BusinessProfileForm` and `PropertyList` pages.
  - Connect to `/properties` endpoint.
  - Style with Tailwind (dark theme).
  - Prompt `03-frontend-skeleton`.

- **Hour 12-18**: Feature completion
  - Implement property selection and calling `/analyze`.
  - Build `AnalysisCard` UI to display results (score, cost, compliance).
  - Use mock data to ensure UI is working.
  - Continue writing tests (frontend & backend).

- **Hour 18-24**: Integrations and Refinement
  - Add actual HTTP calls in providers (if keys available) or refine mock data.
  - Implement image overlays (use sample images).
  - Conduct sponsor-specific polish (e.g. AWS note in docs).
  - Prompt `04-integrations`.

- **Hour 24-30**: Compliance Agent & Criteria scaling
  - Implement compliance logic with at least 2 rules (parking, ADA).
  - Ensure criteria YAML drives scoring. Test adding a new criterion (prompt `scale-criteria`).
  - Polish output formatting (currency, missing data handling).

- **Hour 30-34**: Demo preparation
  - Fill documentation files (like ones above) if needed.
  - Final UI polish: make sure colors, alignment, logos are presentable.
  - Run through the demo runbook script and fix any issues.
  - Add any Sponsor acknowledgments, confirm PRD alignment.

- **Hour 34-36**: Buffer
  - Handle last-minute issues, commit final code.
  - Prepare the DevPost submission (use docs content).
  - Ensure everything runs from a fresh clone.
```

## DECISIONS_AND_RISKS.md

Major design decisions and potential risks.

```
# Key Decisions and Risks

## Decisions

- **Technology Stack**: Chosen Next.js + FastAPI for speed of development and familiarity. Justified by ease of using TypeScript UI with Python backend.
- **Criteria Config**: Decided to use YAML for criteria registry for flexibility. Requires implementing a loader.
- **Mock Data First**: We'll build with mock data providers to ensure core logic works; real API integration is secondary.
- **Simple Cost Model**: Use fixed ranges and percentages. This is easier to understand and tune during hackathon.
- **Compliance Scope**: Limited to a few checkable items (parking, ADA). Full health code enforcement is out of scope.
- **UI Theme**: Dark theme with accent (as per preference). Will use Tailwind for rapid styling.
- **Agent vs. Deterministic**: Although we frame it as an "AI agent," most logic is hard-coded rules. We will not rely heavily on a live LLM to avoid unpredictability.

## Risks

- **Overambitious Scope**: Risk: Trying to integrate all APIs (CoStar, Matterport, Vexcel) may not be feasible. Mitigation: Focus on mock data with realistic fixtures.
- **Complexity of Compliance**: Risk: Getting actual zoning rules correct for any city is hard. Mitigation: Only implement one city’s rules and clearly label as example.
- **Time**: Risk: Building image overlays and full UI might take longer than planned. Mitigation: Fall back to simpler presentation (e.g. static images with captions).
- **Agent Prompt Misuse**: Risk: Using an LLM to generate code or logic could produce errors. Mitigation: Review and test all generated code.
- **Integration Dependencies**: Risk: External API keys missing. Mitigation: Provide clear instructions to add `.env` keys and have a robust mock mode.
- **Demonstration Issues**: Risk: Live demo could fail if any part breaks. Mitigation: Have a recorded video as backup and ensure mock mode always works.
- **Legal/Copyright**: Risk: Using Matterport or Vexcel imagery may have licensing issues. Mitigation: Use only publicly available or sample images.
- **Data Accuracy**: Risk: Estimate inaccuracies. Mitigation: Emphasize that costs are estimates and highlight uncertainty in UI.
```

## PROMPTS/00-bootstrap.md

First prompt: Set up project structure and install dependencies.

```
Run the following steps to bootstrap the project:

1. Create the root directory and navigate into it:
   ```bash
   mkdir turnkey-matchmaker
   cd turnkey-matchmaker
   ```
2. Initialize Git and NPM/Node:
   ```bash
   git init
   npm init -y
   ```
3. Create folders for backend, frontend, docs, prompts:
   ```bash
   mkdir backend frontend docs prompts
   ```
4. Initialize a Python virtual environment for backend:
   ```bash
   cd backend
   python3 -m venv venv
   source venv/bin/activate
   pip install fastapi uvicorn pydantic sqlmodel requests pytest
   pip freeze > requirements.txt
   cd ..
   ```
5. Initialize a Next.js project:
   ```bash
   cd frontend
   npx create-next-app@latest . --ts --use-tailwind --eslint
   ```
   - If prompted, choose TypeScript, Tailwind CSS.
   - Skip installing example components if asked.
6. Add Tailwind CSS and configure dark theme:
   ```bash
   npm install @tailwindcss/forms @heroicons/react
   ```
   Update `tailwind.config.js` to enable dark mode (e.g. `darkMode: 'class'`). Set default theme colors (navy background, teal accent).
7. Set up `.gitignore`:
   Go back to root and create a `.gitignore` file (see `.gitignore` section).
8. Create an `app` directory for FastAPI under `backend/`:
   ```bash
   cd backend
   mkdir app
   cd app
   mkdir routers models providers services tests
   touch main.py
   ```
9. Create placeholder files for docs and prompts:
   ```bash
   cd ../../docs
   touch PROJECT_BRIEF.md PRD.md ARCHITECTURE.md BACKEND.md API_CONTRACT.md DATA_MODELS.md AGENT_ORCHESTRATION.md COMPLIANCE_AGENT.md COMPLIANCE_RULE_SOURCES.md VISION_OVERLAYS.md COST_ENGINE.md CRITERIA_REGISTRY.md FRONTEND_DESIGN.md INTEGRATIONS.md SECURITY_AND_ENV.md SPONSOR_STRATEGY.md TEST_PLAN.md DEMO_RUNBOOK.md BUILD_PLAN.md DECISIONS_AND_RISKS.md
   cd ../prompts
   touch 00-bootstrap.md 01-backend-skeleton.md 02-agent-workflow.md 03-frontend-skeleton.md 04-integrations.md 05-demo-polish.md scale-criteria.md
   cd ..
   ```
10. Copy `.env.example` to `backend/.env` (if `.env.example` exists) and note where to put API keys.

After these steps, the repository should have the basic structure. Commit changes:
```bash
git add .
git commit -m "Bootstrap project structure"
```

```

## PROMPTS/01-backend-skeleton.md

This prompt instructs creating the basic FastAPI app with sample endpoints.

```
In this step, set up the backend scaffolding:

1. **Create FastAPI App**:
   - In `backend/app/main.py`, write code to create a FastAPI app:
     ```python
     from fastapi import FastAPI
     app = FastAPI()
     @app.get("/health")
     def health():
         return {"status": "ok"}
     ```
2. **Routers and Endpoints**:
   - In `backend/app/routers/`, create two files: `properties.py` and `analyze.py`.
   - `properties.py`: Define a GET route `/api/v1/properties` that accepts query parameters (`business_type`, `city`) and returns a JSON list of property dicts (hardcode 2 sample properties for now).
   - `analyze.py`: Define a POST route `/api/v1/analyze` that accepts a JSON body with keys `"business_profile"` and `"property_ids"`, and returns a dummy JSON report (you can copy the structure from API_CONTRACT.md but fill with placeholder values).
3. **Include Routers in main**:
   - In `main.py`, add:
     ```python
     from .routers import properties, analyze
     app.include_router(properties.router, prefix="/api/v1")
     app.include_router(analyze.router, prefix="/api/v1")
     ```
4. **Run the App**:
   - In the `backend/` folder, activate virtualenv and run:
     ```bash
     uvicorn app.main:app --reload
     ```
   - Verify by visiting `http://localhost:8000/health` (should return `{"status":"ok"}`).
   - Test `http://localhost:8000/api/v1/properties?business_type=restaurant&city=Austin` and `curl` or use browser to see the hardcoded sample.

5. **Database Setup (Optional)**:
   - If using SQLite, create `backend/app/db.py` with SQLModel engine setup.
   - For now, you can skip actual DB and just use in-memory or fixtures.

6. **Requirements Update**:
   - Ensure `requirements.txt` includes all needed libraries (`fastapi`, `uvicorn`, `pydantic`, `sqlmodel`, `pytest`, `requests`, etc.). Use `pip freeze`.

7. **Commit**:
   ```bash
   git add backend/app
   git commit -m "Backend skeleton with FastAPI app and placeholder endpoints"
   ```

Ensure the API endpoints return plausible data structures. This completes the backend skeleton.

```

## PROMPTS/02-agent-workflow.md

This prompt is for implementing the core analysis logic (agents) in the backend.

```
Next, implement the main analysis workflow:

1. **Models**:
   - In `backend/app/models/`, create Pydantic models:
     - `BusinessProfile`: with fields `type: str`, `details: str`, `city: str`, `state: str`.
     - `Property`: as per DATA_MODELS (id, address, city, rent, etc).
     - `AnalysisResult`: as per API_CONTRACT.
   - Use `Field(...)` for defaults if needed.

2. **Criteria Loading**:
   - Place the provided `criteria.yaml` at `backend/criteria.yaml`.
   - In `services/criteria_manager.py`, write a function to load this YAML and parse it into objects or dicts (use `pyyaml` or similar).
   - Ensure each criterion is accessible by `id`.

3. **Cost Engine (`services/cost_engine.py`)**:
   - Implement basic functions to calculate costs:
     - Example: `estimate_kitchen_cost(has_kitchen: bool) -> (min_cost, max_cost)`.
     - Use static values or load from a JSON.
   - A function `estimate_cost(missing_items: List[str], profile) -> (min, max)` that sums up.

4. **Compliance Engine (`services/compliance_engine.py`)**:
   - Implement functions for each compliance check:
     - `check_parking(visible: int, required: int) -> status, notes`.
     - `check_ada(door_width: float) -> status, notes`.
   - Returns PASS/RISK/UNKNOWN strings.

5. **Agent Orchestrator (`services/agent_orchestrator.py`)**:
   - Write a function `analyze_properties(profile, properties_list) -> List[AnalysisResult]`.
   - For each property:
     - Mock observations: e.g. `observations = {"door_width": 36.0, "parking_count": 15}`. (Eventually replace with real detection.)
     - Determine missing items: compare profile needs vs observations.
     - Call cost and compliance functions.
     - Compute a placeholder score (e.g. random or based on rent vs cost).
     - Populate an `AnalysisResult` instance for each.

6. **Connect Endpoints**:
   - In `backend/app/routers/analyze.py`, parse the request into `BusinessProfile`, then call the orchestrator:
     ```python
     @router.post("/analyze")
     def analyze(profile: BusinessProfile, property_ids: List[str]):
         # Fetch properties by ID (using provider or DB)
         props = [get_property_by_id(pid) for pid in property_ids]
         results = analyze_properties(profile, props)
         return {"business_type": profile.type, "results": results}
     ```
   - For now, `get_property_by_id` can fetch from a static list.

7. **Testing the Flow**:
   - After implementing, restart the server and test the flow:
     ```bash
     curl -X POST http://localhost:8000/api/v1/analyze \
       -H "Content-Type: application/json" \
       -d '{"business_profile": {"type":"restaurant","details":"40 seats","city":"Austin","state":"TX"}, "property_ids":["property-123"]}'
     ```
   - Ensure JSON is returned with the structure (even with dummy values).

8. **Error Handling**:
   - If any step fails, return an appropriate HTTP error with a message.
   - For example, if `property_ids` are empty, return 400.

9. **Commit**:
   ```bash
   git add backend/app
   git commit -m "Implement agent workflow: cost estimation and compliance checks"
   ```

At the end of this step, the backend should be able to take a business profile and return an analysis result (even if placeholder data). Test with Pytest on any functions implemented.

```

## PROMPTS/03-frontend-skeleton.md

This prompt covers setting up the Next.js frontend basic structure.

```
Set up the frontend skeleton in `frontend/`:

1. **Home Page (Profile Form)**:
   - Edit `pages/index.tsx`:
     - Create a form with fields:
       - `select` for business type (`restaurant`, `clinic`, etc.).
       - `input type="text"` for details (placeholder example: "40-seat restaurant, need kitchen and parking").
       - `input` for city, state.
       - A "Find Spaces" submit button.
     - On submit, navigate to a property results page (e.g. `/properties` route) with query params or via state.

2. **Properties Page**:
   - Create `pages/properties.tsx`:
     - On mount, read query parameters (business type, location).
     - Fetch from the backend:
       ```
       const res = await fetch(`/api/v1/properties?business_type=${type}&city=${city}`);
       const properties = await res.json();
       ```
     - Display results in a grid of `PropertyCard` components.
   - Each `PropertyCard` shows address, city, size, rent, thumbnail image.
   - Include a checkbox or button to select a property for comparison.

3. **Comparison Button**:
   - On the Properties page, add a "Compare Selected" button.
   - When clicked, gather selected property IDs and send a POST request to `/api/v1/analyze`.
   - Then navigate to `/analysis` page or display results.

4. **Analysis Page (`pages/analysis.tsx`)**:
   - Parse analysis results from API (similar to how you handled /properties).
   - For each property in results, render an `AnalysisCard`:
     - Show property address and score.
     - Show total cost range (format as currency).
     - List compliance statuses (colored indicators).
     - Show breakdown of cost (list).
     - Show any landlord questions.
   - Style using cards or panels.

5. **Styling (Tailwind)**:
   - Ensure dark background: in `globals.css`, set `bg-slate-900` for `body`.
   - Use Tailwind classes like `bg-slate-800 rounded-lg p-4 mb-4` for cards.
   - Buttons: `bg-cyan-500 text-white`.
   - Navigation: Add a basic header with app name on all pages.

6. **State Management**:
   - Simple: use React `useState` or `useRouter` query strings. No need for complex state.

7. **Running Frontend**:
   ```bash
   cd frontend
   npm run dev
   ```
   - Ensure the app loads at `http://localhost:3000` with no errors.

8. **Testing**:
   - Check that form submission triggers a network request (use browser dev tools).
   - Verify data flows from property list to analysis.

9. **Commit**:
   ```bash
   git add frontend
   git commit -m "Frontend skeleton: profile form, property list, and analysis pages"
   ```

After this, the UI should allow entering a profile, listing some mock properties, and receiving an analysis (with placeholder data). Verify basic navigation and fetch calls.

```

## PROMPTS/04-integrations.md

Adding external data integration and advanced features.

```
Integrate data sources and enhance functionality:

1. **CoStar Integration**:
   - In `backend/app/providers/costar_provider.py`:
     - If `COSTAR_API_KEY` is present in `.env`, implement a function to query CoStar (using `requests`). If not, default to reading `fixtures/properties.json`.
     - Map CoStar fields to our `Property` model.
   - Update `/properties` endpoint to use `costar_provider.search_properties`.

2. **Matterport Integration**:
   - In `providers/matterport_provider.py`, add:
     ```python
     def get_interior_images(property_id):
         # If MATTERPORT_API_KEY exists, call Matterport API
         # Else, return a static image URL from fixtures or static files
         return {"floor_plan_url": "...", "matterport_url": None}
     ```
   - Backend: modify analysis to attach these URLs to results.

3. **Vexcel Integration**:
   - In `providers/vexcel_provider.py`, add a similar stub:
     ```python
     def get_aerial_image(address):
         # Use coordinates or address to fetch; if no key, return sample image path
         return {"aerial_url": "static/aerials/sample.jpg"}
     ```
   - Backend: call this and include `aerial_url` in results.

4. **Overlay Annotations**:
   - (At least record the intention: in `VisionOverlays`, annotate known points.)
   - Ensure the analysis result includes coordinates or descriptions for overlays (e.g. store in `AnalysisResult`).

5. **Frontend Enhancements**:
   - On the Analysis page, use the returned image URLs:
     - For aerial, use `<img src={aerial_url} />` and overlay using absolute-positioned divs (if coordinates given).
     - For Matterport, if a URL is provided, embed as `<iframe>` (Matterport embed code).
   - Show a placeholder if no image available.

6. **Compliance Rule Data**:
   - Make sure `compliance_engine` uses any relevant thresholds from `criteria.yaml`.
   - Example: if parking rule says min_ratio=1, compute required spaces as seats/20.

7. **Dynamic Criteria Display**:
   - In `frontend`, load `criteria.yaml` (or have backend send descriptions).
   - Display criteria descriptions and weights in a table, if needed.

8. **Error Handling**:
   - If any API call fails (no internet, bad key), catch exceptions and fallback to mock data.
   - Ensure UI shows an error message if analysis fails.

9. **Review Integration Flow**:
   - Test end-to-end with mock data now replaced by fixture logic.
   - Adjust CORS or proxy if needed (Next.js dev proxy or `http://localhost:8000`).

10. **Commit**:
    ```bash
    git add backend/providers backend/services frontend/components
    git commit -m "Add providers for CoStar/Matterport/Vexcel and image display in frontend"
    ```
```

## PROMPTS/05-demo-polish.md

Final prompt: polish UI, fix any issues, prepare for demo.

```
Final refinements before demo:

1. **UI Polish**:
   - Ensure colors are consistent. Add app icon or logo (if available).
   - Add spinner or loading indicator on analysis request.
   - Add tooltips or info icons on compliance labels.
   - Ensure fonts and spacing look neat.

2. **Content Completeness**:
   - Make sure every piece of data returned by backend is shown in UI (cost breakdown, compliance notes, etc).
   - If some fields are empty, show a placeholder like "N/A".

3. **Responsive Check**:
   - Shrink browser window to simulate mobile. Fix any layout issues.

4. **Mock Scenario**:
   - Create a demo profile and save sample API responses as fixtures.
   - Use those to test the flow once more. Example: Business Profile "Restaurant, 40 seats", Properties "Lease A" and "Lease B".

5. **Testing**:
   - Run all tests (`pytest`, `npm test`). Fix any failing tests.
   - Add any missing edge-case tests from TEST_PLAN.md.

6. **Criteria Scaling Test**:
   - As a final check, open `criteria.yaml` and add a new criterion entry (e.g., "exterior_paint_quality").
   - See if the system can load it without code changes and affects scoring.
   - Write a test to confirm that new criterion appears in the scoring JSON.

7. **Documentation Finalization**:
   - Ensure all `.md` docs are filled out (the ones in `docs/`).
   - Update README with current instructions if anything changed.
   - Verify `.env.example` lists all variables from code.

8. **Clean up**:
   - Remove any debug code or console logs.
   - Commit final changes:
     ```bash
     git add .
     git commit -m "Final polish before demo"
     ```

Once complete, the app should be ready to showcase. Verify the demo runbook steps from DEMO_RUNBOOK.md with this final version.

```

## PROMPTS/scale-criteria.md

A special prompt to increase the number of criteria by editing the config.

```
This prompt focuses on adding more criteria without changing code:

1. **Add a New Criterion**:
   - In `criteria.yaml`, append an entry for a new criterion, e.g.:
     ```yaml
     - id: "window_visibility"
       description: "Restaurant windows visible from street"
       domain: "marketing"
       weight: 5
       hard_block: false
       evaluator: "check_window_visibility"
       required_inputs: ["window_area"]
       missing_data_policy: "ignore"
       evidence_required: false
       source: "Business Importance"
       thresholds:
         min_area: 10
       applicable_jurisdictions: ["ALL"]
     ```
   - Also increase existing criteria weights to total 100 if needed (normalization is allowed by code).

2. **Implement Evaluator Stub**:
   - In `backend/app/services/compliance_engine.py` or `criteria_manager.py`, add a stub function `check_window_visibility(window_area, min_area) -> status, notes` that simply returns PASS if `window_area >= min_area`, else UNKNOWN.

3. **Test Scaling**:
   - Rerun the analysis endpoint; it should now include the new criterion in scoring.
   - Write a unit test: simulate a property with `window_area` below threshold and ensure the score reflects the change (the max score should adjust based on new weight).
   - Ensure no code errors occur on loading the updated `criteria.yaml`.

4. **Frontend**:
   - Confirm that the frontend does not break; it should automatically display the new criterion in any criteria tables (if implemented).

This demonstrates that criteria can be scaled by config alone. Commit your changes:

```bash
git add backend/criteria.yaml backend/app/services
git commit -m "Add 'window_visibility' criterion to criteria.yaml"
```

```

## .env.example

Example environment variables file (at the repo root or `backend/`).

```
# Copy this file to .env and fill in your keys.

# CoStar API (Commercial real estate)
COSTAR_API_KEY=your_costar_api_key_here

# Matterport API (3D property tours)
MATTERPORT_API_KEY=your_matterport_api_key_here

# Vexcel Aerial Imagery
VEXCEL_API_KEY=your_vexcel_api_key_here

# Geocoding (e.g. Google Maps, OpenCage)
GEOCODING_API_KEY=your_geocoding_api_key_here

# Anthropic / Claude API (if using AI for NLP)
ANTHROPIC_API_KEY=your_anthropic_api_key_here

# Any other keys (e.g. AWS credentials if deployed)
```

## .gitignore

A sample `.gitignore` to exclude unnecessary files.

```
# Node and Next.js
frontend/node_modules/
frontend/.next/
frontend/out/
frontend/.env.local

# Python and FastAPI
backend/venv/
backend/*.sqlite3
backend/*.db
backend/__pycache__/
backend/**/*.pyc
backend/.env
backend/.env.local

# General
.DS_Store
*.log
```

## Sample `criteria.yaml`

An example criteria registry file.

```
# criteria.yaml

- id: "parking_sufficiency"
  description: "Sufficient parking for business size"
  domain: "regulatory"
  weight: 15
  hard_block: false
  evaluator: "parking_checker"
  required_inputs:
    - "visible_parking_count"
    - "business_required_parking"
  missing_data_policy: "assume_risk"
  evidence_required: true
  source: "Local Zoning Code"
  thresholds:
    min_ratio: 1   # 1 space per 20 seats
  applicable_jurisdictions: ["ALL"]

- id: "ada_accessibility"
  description: "Meets ADA accessibility standards"
  domain: "safety"
  weight: 10
  hard_block: false
  evaluator: "ada_checker"
  required_inputs: ["door_width_inches"]
  missing_data_policy: "assume_risk"
  evidence_required: true
  source: "Americans with Disabilities Act"
  thresholds:
    min_width: 32
  applicable_jurisdictions: ["ALL"]

- id: "kitchen_equipment"
  description: "Existing commercial kitchen equipment"
  domain: "space"
  weight: 20
  hard_block: false
  evaluator: "kitchen_checker"
  required_inputs: ["kitchen_equipment_visible"]
  missing_data_policy: "assume_cost"
  evidence_required: false
  source: "Restaurant Buildout Standards"
  thresholds: {}
  applicable_jurisdictions: ["ALL"]

- id: "bathroom_count"
  description: "Sufficient restrooms for occupancy"
  domain: "safety"
  weight: 10
  hard_block: false
  evaluator: "bathroom_checker"
  required_inputs:
    - "bathrooms_visible"
    - "business_required_bathrooms"
  missing_data_policy: "assume_risk"
  evidence_required: true
  source: "International Plumbing Code"
  thresholds: {}
  applicable_jurisdictions: ["ALL"]

- id: "fire_safety"
  description: "Fire safety compliance"
  domain: "safety"
  weight: 0
  hard_block: true
  evaluator: "fire_safety_checker"
  required_inputs: ["fire_extinguisher_present"]
  missing_data_policy: "assume_risk"
  evidence_required: true
  source: "Local Fire Code"
  thresholds: {}
  applicable_jurisdictions: ["ALL"]
```

## Fixture: Sample property JSON (`backend/fixtures/properties.json`)

Example data returned by `costar_provider` in mock mode.

```
[
  {
    "id": "property-123",
    "address": "123 Elm Street",
    "city": "Austin",
    "state": "TX",
    "zip": "78701",
    "size_sqft": 2000,
    "rent": 4000,
    "matterport_url": null,
    "image_url": "/images/property-123.jpg"
  },
  {
    "id": "property-456",
    "address": "456 Oak Avenue",
    "city": "Austin",
    "state": "TX",
    "zip": "78702",
    "size_sqft": 1800,
    "rent": 4800,
    "matterport_url": null,
    "image_url": "/images/property-456.jpg"
  }
]
```

Use these fixtures when CoStar/Vexcel APIs are not available.

---

**Note:** These files contain all the information and instructions needed to run Claude Code in "phases" to generate the actual code. Each prompt file (`PROMPTS/xx-*.md`) is a set of tasks the Claude agent will execute sequentially. The `.env.example`, `.gitignore`, `criteria.yaml`, and fixture files should be placed at the root of the appropriate directory as indicated. Use this documentation as the single source of truth for the project’s structure and behavior.

