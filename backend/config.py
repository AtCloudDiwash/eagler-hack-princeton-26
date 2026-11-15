"""Settings (from backend/.env) and YAML config loading (reloaded when the file changes)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BACKEND_DIR / "config"
FIXTURES_DIR = BACKEND_DIR / "fixtures"
load_dotenv(BACKEND_DIR / ".env")


def _key(name: str) -> str | None:
    value = (os.getenv(name) or "").strip()
    return None if not value or value.startswith("your_") else value


class Settings:
    vexcel_api_key = _key("VEXCEL_API_KEY")
    vexcel_base_url = (os.getenv("VEXCEL_API_BASE_URL") or "https://api.vexcelgroup.com/v2").rstrip("/")
    # LLM: the local Codex CLI with the user's own login (~/.codex). Empty model = the one in ~/.codex/config.toml.
    codex_bin = (os.getenv("CODEX_BIN") or "").strip() or None
    codex_model = (os.getenv("CODEX_MODEL") or "").strip() or None
    codex_reasoning_effort = (os.getenv("CODEX_REASONING_EFFORT") or "low").strip()
    codex_timeout_s = float(os.getenv("CODEX_TIMEOUT_S") or 180)
    codex_max_concurrency = int(os.getenv("CODEX_MAX_CONCURRENCY") or 4)
    # Fallback chain, tried in order (codex, claude, ollama). Exhausted providers are skipped for a cooldown.
    llm_providers = [p.strip().lower() for p in (os.getenv("LLM_PROVIDERS") or "codex,claude,ollama").split(",") if p.strip()]
    llm_cooldown_s = float(os.getenv("LLM_COOLDOWN_S") or 1200)
    claude_bin = (os.getenv("CLAUDE_BIN") or "").strip() or None
    claude_model = (os.getenv("CLAUDE_MODEL") or "sonnet").strip()
    claude_timeout_s = float(os.getenv("CLAUDE_TIMEOUT_S") or 180)
    claude_max_concurrency = int(os.getenv("CLAUDE_MAX_CONCURRENCY") or 4)
    ollama_base_url = (os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
    ollama_model = (os.getenv("OLLAMA_MODEL") or "qwen3:8b").strip()
    census_api_key = _key("CENSUS_API_KEY")
    # Neighborhood data: Census LODES (jobs + employed residents per block; public, cached on disk) and a
    # public OSRM foot router for walking times.
    lodes_dir = Path(os.getenv("LODES_DIR") or BACKEND_DIR / "data" / "lodes")
    lodes_year = int(os.getenv("LODES_YEAR") or 2023)
    walk_router_url = os.getenv("WALK_ROUTER_URL") or "https://routing.openstreetmap.de/routed-foot"
    matterport_api_key = _key("MATTERPORT_API_KEY")
    matterport_api_secret = _key("MATTERPORT_API_SECRET")
    # Optional sandbox token (sees only the account's demo model): for development and the query contract test.
    matterport_sandbox_api_key = _key("MATTERPORT_SANDBOX_API_KEY")
    matterport_sandbox_api_secret = _key("MATTERPORT_SANDBOX_API_SECRET")
    database_path = Path(os.getenv("DATABASE_PATH") or "./turnkey.db")
    _origins = [o.strip() for o in (os.getenv("CORS_ORIGINS") or "http://localhost:3000,http://localhost:3001").split(",") if o.strip()]
    # localhost and 127.0.0.1 are the same machine but different browser origins: allow both spellings.
    cors_origins = list(dict.fromkeys(_origins + [o.replace("//localhost", "//127.0.0.1") for o in _origins] + [o.replace("//127.0.0.1", "//localhost") for o in _origins]))
    # Agent limits: keep investigations purposeful and bounded.
    agent_max_model_calls = int(os.getenv("AGENT_MAX_MODEL_CALLS") or 8)
    agent_max_tool_calls = int(os.getenv("AGENT_MAX_TOOL_CALLS") or 8)
    agent_timeout_s = float(os.getenv("AGENT_TIMEOUT_S") or 240)
    # Whole-analysis deadline: agents, follow-ups and the narrative all fit inside it (follow-ups are skipped
    # when little time is left). Generous by default so normal analyses are unaffected.
    analysis_timeout_s = float(os.getenv("ANALYSIS_TIMEOUT_S") or 900)
    http_user_agent = "turnkey-matchmaker/0.1 (hackathon prototype)"

    @property
    def db_file(self) -> Path:
        p = self.database_path
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


settings = Settings()

_cache: dict[Path, tuple[float, Any]] = {}


def load_yaml(name: str) -> Any:
    path = CONFIG_DIR / name
    mtime = path.stat().st_mtime
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    _cache[path] = (mtime, data)
    return data


def business_types() -> dict[str, dict]:
    return load_yaml("business_types.yaml")


def business(business_type: str) -> dict:
    types = business_types()
    return types.get(business_type) or types["restaurant"]


def metrics_registry() -> dict[str, dict]:
    return load_yaml("metrics.yaml")


def place_groups() -> dict[str, dict]:
    return load_yaml("place_groups.yaml")


def costs_config() -> dict:
    return load_yaml("costs.yaml")


def occupancy_codes() -> dict[str, dict]:
    return load_yaml("occupancy_codes.yaml")


def needs_registry() -> dict[str, dict]:
    return load_yaml("needs.yaml")


def jurisdictions() -> dict[str, dict]:
    return load_yaml("jurisdictions.yaml")


@lru_cache(maxsize=1)
def roof_condition_labels() -> dict[int, str]:
    # From the Vexcel /property/extract spec (min-roof-condition): 1 Bad, 2 Poor, 3 Fair, 4 Good, 5 Great.
    return {1: "Bad", 2: "Poor", 3: "Fair", 4: "Good", 5: "Great"}
