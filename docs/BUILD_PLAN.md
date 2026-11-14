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
