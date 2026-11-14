"""Fallback chain tests (Codex → Claude Code → Ollama) with fake CLIs, fully offline."""
from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import pytest  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from config import settings  # noqa: E402
from services import llm  # noqa: E402
from services.claude_chat import ChatClaudeCLI, ClaudeUsageLimitError  # noqa: E402

FAKE_CODEX_LIMIT = textwrap.dedent('''\
    #!/bin/sh
    echo invoked >> "$(dirname "$0")/codex_calls.log"
    echo "ERROR: You've hit your usage limit. Try again at 8:14 PM." >&2
    exit 1
''')

FAKE_CLAUDE = textwrap.dedent('''\
    #!/usr/bin/env python3
    """Fake `claude -p --output-format json [--json-schema S]`: tool turns call get_roof once, then report."""
    import json, sys
    args = sys.argv[1:]
    assert "-p" in args and "--tools" in args and args[args.index("--tools") + 1] == ""
    assert "--no-session-persistence" in args and "--strict-mcp-config" in args
    schema = json.loads(args[args.index("--json-schema") + 1]) if "--json-schema" in args else None
    prompt = sys.stdin.read()
    if schema and schema.get("required") == ["kind", "content", "tool_calls"]:
        if "[TOOL RESULT" not in prompt:
            out = {"kind": "tool_calls", "content": "", "tool_calls": [{"name": "get_roof", "arguments_json": json.dumps({"pid": "P1"})}]}
        else:
            report = {"summary": "Claude checked the roof.", "metric_assessments": [], "findings": [], "missing_information": [], "contradictions": [], "followups": []}
            out = {"kind": "tool_calls", "content": "", "tool_calls": [{"name": "AgentOutput", "arguments_json": json.dumps(report)}]}
    elif schema:
        out = {"name": "via-claude", "count": 7}
    else:
        out = None
    print(json.dumps({"type": "result", "is_error": False, "result": "plain" if out is None else json.dumps(out), "structured_output": out}))
''')

FAKE_CLAUDE_LIMIT = textwrap.dedent('''\
    #!/bin/sh
    echo '{"type":"result","is_error":true,"result":"Claude AI usage limit reached","api_error_status":429}'
    exit 1
''')


def _exe(path: Path, body: str) -> str:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


class Out(BaseModel):
    name: str
    count: int


@pytest.fixture(autouse=True)
def chain(tmp_path, monkeypatch):
    llm.reset_cooldowns()
    monkeypatch.setattr(settings, "codex_bin", _exe(tmp_path / "codex", FAKE_CODEX_LIMIT))
    monkeypatch.setattr(settings, "claude_bin", _exe(tmp_path / "claude", FAKE_CLAUDE))
    monkeypatch.setattr(settings, "llm_providers", ["codex", "claude"])
    yield tmp_path
    llm.reset_cooldowns()


def test_codex_usage_limit_falls_back_to_claude_and_cools_down(chain):
    async def run():
        counts = llm.track_usage()
        notes: list[str] = []
        llm.on_fallback(notes.append)
        first = await llm.chat_model().with_structured_output(Out).ainvoke("go")
        second = await llm.chat_model().with_structured_output(Out).ainvoke("again")
        return first, second, counts, notes

    first, second, counts, notes = asyncio.run(run())
    assert first == Out(name="via-claude", count=7) == second
    assert counts == {"claude": 2}
    assert notes and "switching to Claude Code" in notes[0]
    # Codex was tried once, then skipped during its cooldown.
    assert (chain / "codex_calls.log").read_text().count("invoked") == 1


def test_all_providers_failing_raises_one_clear_error(chain, monkeypatch):
    monkeypatch.setattr(settings, "claude_bin", _exe(chain / "claude-limit", FAKE_CLAUDE_LIMIT))
    with pytest.raises(llm.AllProvidersFailedError, match="codex: .*usage limit.*claude: .*usage limit"):
        llm.chat_model().with_structured_output(Out).invoke("go")


def test_claude_usage_limit_is_exhaustion(chain):
    with pytest.raises(ClaudeUsageLimitError):
        ChatClaudeCLI(binary=_exe(chain / "c2", FAKE_CLAUDE_LIMIT)).invoke("hi")


def test_deep_agent_runs_through_fallback(chain):
    from deepagents import create_deep_agent
    from langchain.agents.structured_output import ToolStrategy
    from langchain_core.tools import tool

    import agents.base  # noqa: F401  (registers the "turnkey" harness profile)
    from schemas import AgentOutput

    calls = []

    @tool
    def get_roof(pid: str) -> dict:
        """Roof data for a property."""
        calls.append(pid)
        return {"ac_units_detected": 0}

    async def run():
        counts = llm.track_usage()
        graph = create_deep_agent(model=llm.chat_model(), tools=[get_roof], system_prompt="Investigate.", response_format=ToolStrategy(AgentOutput))
        state = await graph.ainvoke({"messages": [{"role": "user", "content": "Check P1"}]}, {"recursion_limit": 12})
        return state, counts

    state, counts = asyncio.run(run())
    assert calls == ["P1"]
    assert state["structured_response"].summary == "Claude checked the roof."
    assert counts.get("claude", 0) >= 2 and "codex" not in counts


def test_health_reports_every_provider(chain):
    status = asyncio.run(llm.llm_status())
    assert [p["provider"] for p in status["providers"]] == ["codex", "claude"]
    assert {"ok", "provider", "label", "model", "error", "providers"} <= set(status)
