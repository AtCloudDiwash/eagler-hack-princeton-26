"""Settings and config-file loading.

Environment variables come from backend/.env (copy the repo-root .env.example). The YAML
config files are cached and reloaded automatically when they change on disk, so editing
criteria weights or cost bands takes effect on the next request without a restart.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BACKEND_DIR / "config"
FIXTURES_DIR = BACKEND_DIR / "fixtures"

load_dotenv(BACKEND_DIR / ".env")
log = logging.getLogger("turnkey")


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _key(name: str) -> str | None:
    value = (os.getenv(name) or "").strip()
    # Treat the .env.example placeholders as "no key".
    if not value or value.startswith("your_"):
        return None
    return value


class Settings:
    def __init__(self) -> None:
        self.costar_api_key = _key("COSTAR_API_KEY")
        self.matterport_api_key = _key("MATTERPORT_API_KEY")
        self.vexcel_api_key = _key("VEXCEL_API_KEY")
        self.geocoding_api_key = _key("GEOCODING_API_KEY")
        self.anthropic_api_key = _key("ANTHROPIC_API_KEY")
        self.force_mock = _env_flag("USE_MOCK_DATA", default=True)
        self.criteria_path = Path(os.getenv("CRITERIA_PATH") or BACKEND_DIR / "criteria.yaml")
        self.cors_origins = [
            o.strip() for o in (os.getenv("CORS_ORIGINS") or "http://localhost:3000").split(",") if o.strip()
        ]

    def provider_mode(self, key: str | None) -> str:
        """'live' only when mock mode is off and the provider's key is set."""
        return "live" if (not self.force_mock and key) else "mock"

    @property
    def mode_summary(self) -> dict[str, str]:
        return {
            "costar": self.provider_mode(self.costar_api_key),
            "matterport": self.provider_mode(self.matterport_api_key),
            "vexcel": self.provider_mode(self.vexcel_api_key),
        }


settings = Settings()

_yaml_cache: dict[Path, tuple[float, Any]] = {}


def load_yaml(path: Path) -> Any:
    """Load a YAML file, re-reading it only when its modification time changes."""
    mtime = path.stat().st_mtime
    cached = _yaml_cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    _yaml_cache[path] = (mtime, data)
    return data


def business_types() -> dict[str, dict]:
    return load_yaml(CONFIG_DIR / "business_types.yaml")


def cost_config() -> dict:
    return load_yaml(CONFIG_DIR / "costs.yaml")


def jurisdiction_for(city: str | None, state: str | None) -> dict:
    """Rules for '<city>-<state>', falling back to the generic default."""
    table = load_yaml(CONFIG_DIR / "jurisdictions.yaml")
    key = f"{(city or '').strip()}-{(state or '').strip()}".lower().replace(" ", "-")
    rules = dict(table["default"])
    rules.update(table.get(key, {}))
    rules["key"] = key if key in table else "default"
    return rules
