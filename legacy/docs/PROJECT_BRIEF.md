# Project Brief – Turnkey Matchmaker

**Objective:** Build an AI-assisted web application that helps entrepreneurs choose commercial real estate by showing the *total cost to open* each space, rather than just rent. This lowers the risk of costly surprises in renovations and compliance issues.

**Users:** First-time or small-business tenants (especially restaurants, clinics, small gyms, etc.) who need to find and evaluate lease spaces. Real estate brokers or property managers could also use it as a decision-support tool.

**Key Problem:** Traditional real estate listings show rent and size, but do not reveal the hidden costs of converting a space. E.g. does the space have restaurant-grade ventilation? Enough plumbing? Suitable parking? Tenants currently spend weeks and money on architects and inspections to answer these questions.

**Proposed Solution:** An agent pipeline (deterministic rules; a local LLM, qwen3:8b on Ollama, reads the free text and explains the finished ranking, with a regex fallback) that:
- Takes user requirements (e.g. "40 seats, kitchen needed, 2 bathrooms" for a restaurant in Houston, TX; a 4-chair dental clinic also works).
- Pulls candidate properties (CoStar-shaped listings; sample listings at real Houston buildings until CoStar access is connected).
- Uses real Vexcel aerial imagery and AI property facts (rooftop HVAC units, roof condition, building footprint, paving) and 3D-tour data (Matterport-shaped fixtures for now) to **observe** existing features.
- Applies rule-based logic to **infer** needed renovations (e.g. install a hood, repair a roof) and compliance checks (zoning or deed restrictions, the city's parking code, ADA, restrooms).
- Outputs a **ranked comparison** of spaces, with an estimated build-out cost range, compliance status, and recommended landlord requests.

**Constraints:** 36-hour hackathon. Must deliver a working MVP that convinces judges: a polished UI demo with real-time analysis of at least two properties for a chosen business type (e.g. restaurant). Hardware integration is not required (this is primarily software, leveraging sponsor-provided data). All features should be prototyped with clarity, even if some data is mocked.

**Success Criteria:**
- Judges can interact with the app live, enter a business scenario, and see instant analysis.
- The app clearly shows why a higher-rent space might be cheaper overall.
- Compliance risks and missing information are highlighted.
- The system is robust, with fallbacks (e.g. offline mode if no live API).
- Code quality is good enough for a hackathon; documentation and prompts ensure reproducibility.

**Status:** MVP built, with live Vexcel data in Houston. See the [README](../README.md) for features and [BUILD_PLAN.md](BUILD_PLAN.md) for phase status.
