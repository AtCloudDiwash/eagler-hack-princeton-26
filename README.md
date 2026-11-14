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
