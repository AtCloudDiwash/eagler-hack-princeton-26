"""Existing databases retain analyses when the separate conversation field is added."""
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import db


def test_old_database_migrates_and_stores_history_separately(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as old:
        old.executescript(db.SCHEMA.replace("  conversation_history TEXT NOT NULL DEFAULT '[]',\n", ""))
        old.execute("INSERT INTO analyses (id,status,created_at,query,intent,property,radius_m) VALUES ('old','queued','today','old request','{}','{}',500)")
    monkeypatch.setattr(db.settings, "database_path", path)
    monkeypatch.setattr(db, "_conn", None)
    try:
        assert db.get_analysis("old")["conversation_history"] == []
        history = [{"role": "user", "text": "need parking"}, {"role": "user", "text": "drop parking"}]
        db.create_analysis("new", "final request", {"needs": []}, {}, 500, conversation_history=history)
        saved = db.get_analysis("new")
        assert saved["query"] == "final request" and saved["intent"]["needs"] == []
        assert saved["conversation_history"] == history
    finally:
        db.conn().close()
