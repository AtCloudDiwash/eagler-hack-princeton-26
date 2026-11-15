"""FastAPI entry point: `uvicorn app.main:app --reload` from backend/."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import BACKEND_DIR, log, settings
from .routers import analyses, analyze, business_types, criteria, health, properties
from .services import llm
from .services.criteria_manager import CriteriaConfigError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
STATIC_DIR = BACKEND_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    modes = {**settings.mode_summary, **health.llm_mode()}
    log.info("Turnkey Matchmaker API starting; provider modes: %s", modes)
    llm.warm_up()  # background: load the Ollama model so the first analysis isn't slow
    log.info("Run history DB: %s", settings.database_url)
    yield


app = FastAPI(
    title="Turnkey Matchmaker API",
    version="1.0.0",
    description="Compare commercial spaces by total occupancy cost, fit-out and compliance.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(CriteriaConfigError)
async def criteria_config_error(_: Request, exc: CriteriaConfigError) -> JSONResponse:
    log.error("criteria registry error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": f"Criteria registry error: {exc}"})


app.include_router(health.router)
for module in (business_types, criteria, properties, analyze, analyses):
    app.include_router(module.router, prefix="/api/v1")

STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
