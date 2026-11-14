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
