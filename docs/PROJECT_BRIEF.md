# Project Brief – Turnkey Matchmaker

**Objective:** Build an AI-assisted web application that helps entrepreneurs choose commercial real estate by showing the *total cost to open* each space, rather than just rent. This lowers the risk of costly surprises in renovations and compliance issues.

**Users:** First-time or small-business tenants (especially restaurants, clinics, small gyms, etc.) who need to find and evaluate lease spaces. Real estate brokers or property managers could also use it as a decision-support tool.

**Key Problem:** Traditional real estate listings show rent and size, but do not reveal the hidden costs of converting a space. E.g. does the space have restaurant-grade ventilation? Enough plumbing? Suitable parking? Tenants currently spend weeks and money on architects and inspections to answer these questions.

**Proposed Solution:** An agent pipeline (deterministic rules, with optional Claude for parsing free text) that:
- Takes user requirements (e.g. "40 seats, kitchen needed, 2 bathrooms, 20 parking spaces" for a restaurant in Austin, TX; a 4-chair dental clinic also works).
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

**Status:** MVP built. See the [README](../README.md) for features and [BUILD_PLAN.md](BUILD_PLAN.md) for phase status.
