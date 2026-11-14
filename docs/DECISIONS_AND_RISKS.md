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
