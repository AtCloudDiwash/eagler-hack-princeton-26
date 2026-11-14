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
