"""Claude Code CLI provider: replies where the model tried to call agent tools natively are rejected."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import pytest  # noqa: E402

from services.claude_chat import ChatClaudeCLI, NativeToolAttemptError  # noqa: E402
from services.cli_chat import TOOL_TURN_SCHEMA  # noqa: E402


def _out(structured: dict, turns: int) -> str:
    return json.dumps({"type": "result", "is_error": False, "num_turns": turns, "result": "", "structured_output": structured})


def test_clean_tool_turn_passes():
    raw = ChatClaudeCLI()._extract(0, _out({"kind": "tool_calls", "content": "", "tool_calls": [{"name": "t", "arguments_json": "{}"}]}, 2), "", "", TOOL_TURN_SCHEMA)
    assert json.loads(raw)["kind"] == "tool_calls"


@pytest.mark.parametrize("structured,turns", [
    ({"kind": "final", "content": "Each tool returned No such tool available.", "tool_calls": []}, 2),
    ({"kind": "final", "content": "I could not gather evidence.", "tool_calls": []}, 7),
])
def test_native_tool_attempt_is_rejected(structured, turns):
    with pytest.raises(NativeToolAttemptError):
        ChatClaudeCLI()._extract(0, _out(structured, turns), "", "", TOOL_TURN_SCHEMA)


def test_plain_structured_output_unaffected():
    raw = ChatClaudeCLI()._extract(0, _out({"business_type": "restaurant"}, 4), "", "", {"properties": {"business_type": {}}})
    assert json.loads(raw)["business_type"] == "restaurant"


def test_retries_twice_then_gives_up(monkeypatch):
    calls = []
    def fake(self, prompt, schema):
        calls.append(prompt)
        raise NativeToolAttemptError("x")
    monkeypatch.setattr("services.cli_chat.CLIChatModel._call_sync", fake)
    with pytest.raises(NativeToolAttemptError):
        ChatClaudeCLI()._call_sync("p", TOOL_TURN_SCHEMA)
    assert len(calls) == 3 and all("Reminder" in c for c in calls[1:])
