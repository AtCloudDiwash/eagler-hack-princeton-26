"""SQLite persistence: analyses (with live event log), discovered properties and an HTTP cache."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

from config import settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
  id TEXT PRIMARY KEY,
  candidate TEXT NOT NULL,       -- Candidate JSON
  raw TEXT,                      -- full Vexcel feature JSON (or null)
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  query TEXT NOT NULL,
  intent TEXT NOT NULL,
  property TEXT NOT NULL,
  radius_m INTEGER NOT NULL,
  events TEXT NOT NULL DEFAULT '[]',
  result TEXT,
  error TEXT
);
CREATE TABLE IF NOT EXISTS searches (
  id TEXT PRIMARY KEY,
  query TEXT NOT NULL,
  intent TEXT NOT NULL,
  location TEXT,
  data_mode TEXT,
  candidate_ids TEXT NOT NULL,   -- JSON list, ranked
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cache (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  created_at REAL NOT NULL
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        settings.db_file.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(settings.db_file, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        cols = {r[1] for r in _conn.execute("PRAGMA table_info(analyses)")}
        # Migrations for databases created before Quick/Deep modes and search grouping.
        for col, ddl in (("mode", "TEXT NOT NULL DEFAULT 'deep'"), ("search_id", "TEXT"), ("base_query", "TEXT"), ("extra_requirements", "TEXT")):
            if col not in cols:
                _conn.execute(f"ALTER TABLE analyses ADD COLUMN {col} {ddl}")
        _conn.commit()
    return _conn


def _exec(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    with _lock:
        cur = conn().execute(sql, params)
        conn().commit()
        return cur


def _one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    with _lock:
        return conn().execute(sql, params).fetchone()


# ---------------------------------------------------------------- cache

def cache_get(key: str, max_age_s: float) -> Any | None:
    row = _one("SELECT value, created_at FROM cache WHERE key = ?", (key,))
    if row and time.time() - row["created_at"] < max_age_s:
        return json.loads(row["value"])
    return None


def cache_set(key: str, value: Any) -> None:
    _exec("INSERT OR REPLACE INTO cache (key, value, created_at) VALUES (?, ?, ?)", (key, json.dumps(value), time.time()))


# ---------------------------------------------------------------- properties

def save_property(candidate: dict, raw: dict | None) -> None:
    _exec(
        "INSERT OR REPLACE INTO properties (id, candidate, raw, created_at) VALUES (?, ?, ?, ?)",
        (candidate["id"], json.dumps(candidate), json.dumps(raw) if raw is not None else None, time.time()),
    )


def get_property(prop_id: str) -> tuple[dict, dict | None] | None:
    row = _one("SELECT candidate, raw FROM properties WHERE id = ?", (prop_id,))
    if not row:
        return None
    return json.loads(row["candidate"]), (json.loads(row["raw"]) if row["raw"] else None)


# ---------------------------------------------------------------- analyses

def create_analysis(analysis_id: str, query: str, intent: dict, prop: dict, radius_m: int, mode: str = "deep",
                    search_id: str | None = None, extra_requirements: str | None = None) -> None:
    _exec(
        "INSERT INTO analyses (id, status, created_at, query, intent, property, radius_m, mode, search_id, base_query, extra_requirements) "
        "VALUES (?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (analysis_id, datetime.now(timezone.utc).isoformat(), query, json.dumps(intent), json.dumps(prop), radius_m, mode, search_id, query, extra_requirements),
    )


def save_search(search_id: str, query: str, intent: dict, location: dict | None, data_mode: str, candidate_ids: list[str]) -> None:
    _exec(
        "INSERT OR REPLACE INTO searches (id, query, intent, location, data_mode, candidate_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (search_id, query, json.dumps(intent), json.dumps(location), data_mode, json.dumps(candidate_ids), datetime.now(timezone.utc).isoformat()),
    )


def get_search(search_id: str) -> dict | None:
    row = _one("SELECT * FROM searches WHERE id = ?", (search_id,))
    if not row:
        return None
    return {
        "id": row["id"], "query": row["query"], "intent": json.loads(row["intent"]), "location": json.loads(row["location"] or "null"),
        "data_mode": row["data_mode"], "candidate_ids": json.loads(row["candidate_ids"]), "created_at": row["created_at"],
    }


def _json_default(o: Any) -> Any:
    return o.model_dump() if hasattr(o, "model_dump") else str(o)


def update_analysis(analysis_id: str, **fields: Any) -> None:
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k} = ?")
        vals.append(json.dumps(v, default=_json_default) if k in {"events", "result"} else v)
    _exec(f"UPDATE analyses SET {', '.join(cols)} WHERE id = ?", (*vals, analysis_id))


def _row_to_analysis(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "query": row["query"],
        "intent": json.loads(row["intent"]),
        "property": json.loads(row["property"]),
        "radius_m": row["radius_m"],
        "mode": row["mode"] if "mode" in row.keys() else "deep",
        "search_id": row["search_id"] if "search_id" in row.keys() else None,
        "base_query": (row["base_query"] if "base_query" in row.keys() else None) or row["query"],
        "extra_requirements": row["extra_requirements"] if "extra_requirements" in row.keys() else None,
        "events": json.loads(row["events"]),
        "result": json.loads(row["result"]) if row["result"] else None,
        "error": row["error"],
    }


def get_analysis(analysis_id: str) -> dict | None:
    row = _one("SELECT * FROM analyses WHERE id = ?", (analysis_id,))
    return _row_to_analysis(row) if row else None


def list_analyses(limit: int = 200) -> list[dict]:
    with _lock:
        rows = conn().execute("SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_analysis(r) for r in rows]


def mark_interrupted() -> None:
    """Analyses left running when the server stopped can never finish; mark them failed."""
    _exec("UPDATE analyses SET status = 'failed', error = 'Server restarted during analysis' WHERE status IN ('queued', 'running')")
