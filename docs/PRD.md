# Product Requirements – Turnkey Matchmaker

## User Stories

1. **Property Search & Filter**
   - As a user, I can select a business profile (e.g. "restaurant", "dental clinic") and input specific requirements (square footage, number of rooms, parking needed).
   - As a user, I can set my location (city or address).
   - The system shows a list of available properties (mocked CoStar listings) matching basic criteria (size, location, rent range).

2. **Space Analysis**
   - As a user, I can select one or more properties and compare them.
   - The system retrieves the property's 3D tour (Matterport) and aerial image.
   - The system extracts visible features (e.g. existing kitchen/bathroom, HVAC units) and measurements (e.g. ADA door widths). In the MVP these facts come from mock fixtures shaped like Matterport/Vexcel output.

3. **Fit-Out Cost Estimation**
   - As a user, I see a breakdown of required renovations with cost ranges (e.g. "Commercial kitchen: \$40k–\$60k", "ADA entrance ramp: \$5k–\$10k").
   - The system uses a deterministic rule-based cost model (`backend/config/costs.yaml`) to estimate ranges, never point estimates.

4. **Compliance Check**
   - As a user, I see a list of compliance items (e.g. parking requirement, ADA rules, health regulations).
   - Each item is marked PASS, RISK, or UNKNOWN, with a brief explanation (e.g. "RISK: 1 restroom visible; 1 more needed for an occupant load of 46"), plus a source citation.

5. **Comparison and Ranking**
   - As a user, I can compare multiple properties side-by-side.
   - The app displays a summary card for each: total estimated cost, a composite score, and key pros/cons.
   - Properties are ranked by lowest first-year cost (cost to open + 12 months rent) among spaces with a fit score of at least `ranking.min_score` (25); weak fits come next and disqualified spaces last.
   - Criteria weights are adjusted in `backend/criteria.yaml` (no settings UI in the MVP).

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

## Acceptance Criteria (status)

- [x] Basic Next.js frontend loads without errors.
- [x] FastAPI backend starts and returns a sample property list at `/api/v1/properties`.
- [x] `POST /api/v1/analyze` returns JSON with observed features (`observations`), cost ranges and compliance results.
- [x] The frontend calls `/api/v1/analyze` and displays results in analysis cards and a comparison table.
- [x] Compliance checks show PASS/RISK/UNKNOWN based on rules in code and config (e.g. ADA 32 in. clear width).
- [x] Criteria weights changed in YAML affect scoring output (hot reload; covered by tests).
- [x] The demo scenario (restaurant, 4 Austin spaces) is fully functional and presentable ([DEMO_RUNBOOK.md](DEMO_RUNBOOK.md)).
