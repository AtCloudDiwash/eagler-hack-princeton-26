In this step, set up the backend scaffolding:

1. **Create FastAPI App**:
   - In `backend/app/main.py`, write code to create a FastAPI app:
     ```python
     from fastapi import FastAPI
     app = FastAPI()
     @app.get("/health")
     def health():
         return {"status": "ok"}
     ```
2. **Routers and Endpoints**:
   - In `backend/app/routers/`, create two files: `properties.py` and `analyze.py`.
   - `properties.py`: Define a GET route `/api/v1/properties` that accepts query parameters (`business_type`, `city`) and returns a JSON list of property dicts (hardcode 2 sample properties for now).
   - `analyze.py`: Define a POST route `/api/v1/analyze` that accepts a JSON body with keys `"business_profile"` and `"property_ids"`, and returns a dummy JSON report (you can copy the structure from API_CONTRACT.md but fill with placeholder values).
3. **Include Routers in main**:
   - In `main.py`, add:
     ```python
     from .routers import properties, analyze
     app.include_router(properties.router, prefix="/api/v1")
     app.include_router(analyze.router, prefix="/api/v1")
     ```
4. **Run the App**:
   - In the `backend/` folder, activate virtualenv and run:
     ```bash
     uvicorn app.main:app --reload
     ```
   - Verify by visiting `http://localhost:8000/health` (should return `{"status":"ok"}`).
   - Test `http://localhost:8000/api/v1/properties?business_type=restaurant&city=Austin` and `curl` or use browser to see the hardcoded sample.

5. **Database Setup (Optional)**:
   - If using SQLite, create `backend/app/db.py` with SQLModel engine setup.
   - For now, you can skip actual DB and just use in-memory or fixtures.

6. **Requirements Update**:
   - Ensure `requirements.txt` includes all needed libraries (`fastapi`, `uvicorn`, `pydantic`, `sqlmodel`, `pytest`, `requests`, etc.). Use `pip freeze`.

7. **Commit**:
   ```bash
   git add backend/app
   git commit -m "Backend skeleton with FastAPI app and placeholder endpoints"
   ```

Ensure the API endpoints return plausible data structures. This completes the backend skeleton.
