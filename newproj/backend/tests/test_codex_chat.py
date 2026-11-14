"""Codex CLI adapter tests. A fake `codex` executable stands in for the real CLI, so these run offline
and exercise the real subprocess path, tool calling through Deep Agents and structured output."""
from __future__ import annotations

import json
import os
import stat
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_PATH", "/tmp/turnkey-test.db")

import pytest  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from services.codex_chat import ChatCodexCLI, build_prompt, parse_tool_turn, strict_schema  # noqa: E402

TOOLS = [{"type": "function", "function": {"name": "get_roof", "description": "Roof data", "parameters": {"type": "object", "properties": {"pid": {"type": "string"}}}}}]


def test_prompt_renders_system_tools_and_tool_results():
    msgs = [
        SystemMessage(content="Be careful."),
        HumanMessage(content="Check P1"),
        AIMessage(content="", tool_calls=[{"name": "get_roof", "args": {"pid": "P1"}, "id": "c1"}]),
        ToolMessage(content='{"ac": 0}', tool_call_id="c1", name="get_roof"),
    ]
    p = build_prompt(msgs, TOOLS, "any")
    assert "Be careful." in p and "get_roof: Roof data" in p
    assert '[ASSISTANT TOOL CALL id=c1] get_roof {"pid": "P1"}' in p and '[TOOL RESULT id=c1 name=get_roof]\n{"ac": 0}' in p
    assert "MUST call at least one tool" in p and "do not run commands" in p.lower()


def test_parse_tool_turn_valid_and_invalid_calls():
    raw = json.dumps({"kind": "tool_calls", "content": "", "tool_calls": [
        {"name": "get_roof", "arguments_json": '{"pid": "P1"}'},
        {"name": "rm_rf", "arguments_json": "{}"},
        {"name": "get_roof", "arguments_json": "not json"},
    ]})
    msg = parse_tool_turn(raw, TOOLS)
    assert [c["args"] for c in msg.tool_calls] == [{"pid": "P1"}]
    assert len(msg.invalid_tool_calls) == 2
    final = parse_tool_turn(json.dumps({"kind": "final", "content": "done", "tool_calls": []}), TOOLS)
    assert final.content == "done" and not final.tool_calls


def test_strict_schema_requires_all_fields_and_forbids_extras():
    class M(BaseModel):
        a: str
        b: list[str] = []
        c: int | None = None

    s = strict_schema(M.model_json_schema())
    assert s["required"] == ["a", "b", "c"] and s["additionalProperties"] is False
    assert "default" not in json.dumps(s)


FAKE_CODEX = textwrap.dedent('''\
    #!/usr/bin/env python3
    """Fake codex CLI: tool turn -> call get_roof once, then return the AgentOutput report; schema turn -> fill schema."""
    import json, sys
    args = sys.argv[1:]
    out = args[args.index("-o") + 1]
    schema = json.load(open(args[args.index("--output-schema") + 1])) if "--output-schema" in args else None
    prompt = sys.stdin.read()
    assert "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in args and "--ignore-user-config" in args
    for builtin in ("write_file", "edit_file", "execute", "write_todos"):
        assert "- " + builtin + ":" not in prompt, builtin  # codex harness profile must strip Deep Agents built-ins
    if schema and schema.get("required") == ["kind", "content", "tool_calls"]:
        if "[TOOL RESULT" not in prompt:
            reply = {"kind": "tool_calls", "content": "", "tool_calls": [{"name": "get_roof", "arguments_json": json.dumps({"pid": "P1"})}]}
        else:
            report = {"summary": "Roof checked.", "metric_assessments": [], "findings": [], "missing_information": ["HVAC unverified"], "contradictions": [], "followups": []}
            reply = {"kind": "tool_calls", "content": "", "tool_calls": [{"name": "AgentOutput", "arguments_json": json.dumps(report)}]}
    elif schema:
        reply = {"name": "Houston", "count": 3}
    else:
        reply = "plain text"
    open(out, "w").write(reply if isinstance(reply, str) else json.dumps(reply))
''')


@pytest.fixture
def fake_codex(tmp_path):
    path = tmp_path / "codex"
    path.write_text(FAKE_CODEX)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def test_structured_output_through_subprocess(fake_codex):
    class Out(BaseModel):
        name: str
        count: int

    llm = ChatCodexCLI(binary=fake_codex, model="test-model").with_structured_output(Out)
    assert llm.invoke("go") == Out(name="Houston", count=3)


def test_deep_agent_loop_runs_tools_via_codex(fake_codex):
    import asyncio

    from deepagents import create_deep_agent
    from langchain.agents.structured_output import ToolStrategy

    import agents.base  # noqa: F401  (registers the "codex" harness profile)
    from schemas import AgentOutput

    calls = []

    @tool
    def get_roof(pid: str) -> dict:
        """Roof data for a property."""
        calls.append(pid)
        return {"ac_units_detected": 0}

    model = ChatCodexCLI(binary=fake_codex, model="test-model")
    graph = create_deep_agent(model=model, tools=[get_roof], system_prompt="Investigate.", response_format=ToolStrategy(AgentOutput))
    state = asyncio.run(graph.ainvoke({"messages": [{"role": "user", "content": "Check P1"}]}, {"recursion_limit": 12}))
    assert calls == ["P1"]
    assert state["structured_response"].missing_information == ["HVAC unverified"]
    # Deep Agents' own file/shell/sub-agent tools are excluded by the codex harness profile.
    bound = model.bind_tools([get_roof])
    assert bound.kwargs["tools"][0]["function"]["name"] == "get_roof"


def test_missing_binary_is_a_clear_error():
    from services.codex_chat import CodexError

    with pytest.raises(CodexError, match="not found"):
        ChatCodexCLI(binary="/nonexistent/codex").invoke("hi")
