"""Shared JSON fixture loading for mock-mode providers."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from ..config import FIXTURES_DIR


@lru_cache(maxsize=None)
def load_fixture(name: str) -> Any:
    with (FIXTURES_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)
