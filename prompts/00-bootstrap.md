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
