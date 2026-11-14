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
