"""LangChain chat model backed by the local Codex CLI (`codex exec`).

Every LLM decision in the app (intent parsing, every Deep Agent step, report extraction, the final
narrative) runs through the Codex CLI on this machine, authenticated with the user's own Codex /
ChatGPT login in ~/.codex. No API key is stored in the app.

How it works
  * Messages are rendered into one transcript prompt and piped to
    `codex exec --ephemeral --sandbox read-only --output-schema <schema> -`.
  * Tool calling: Codex has no API for caller-defined tools, so bound tools are described in the
    prompt and Codex answers through a strict JSON schema {kind, content, tool_calls[]}. The reply
    is converted into a normal LangChain AIMessage with `tool_calls`, so Deep Agents / LangGraph
    execute the tools exactly as with any provider.
  * Structured output: `with_structured_output(Model)` passes the model's JSON Schema (made strict)
    as --output-schema, so Codex can only return schema-valid JSON.
  * Isolation: each call runs in an empty temp directory with a read-only sandbox, ignores the user's
    personal Codex config/rules (plugins, MCP servers, hooks) and is told not to run commands.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import uuid
from pathlib import Path
from typing import Any, Sequence

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

# Known install locations: PATH, then the CLI bundled inside the ChatGPT / Codex desktop app (macOS).
_CANDIDATES = [
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
    "/Applications/Codex.app/Contents/Resources/codex-cli/bin/codex",
    str(Path.home() / ".codex/plugins/.plugin-appserver/codex-cli/bin/codex"),
]

TOOL_TURN_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["kind", "content", "tool_calls"],
    "properties": {
        "kind": {"type": "string", "enum": ["tool_calls", "final"]},
        "content": {"type": "string"},
        "tool_calls": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "arguments_json"],
                "properties": {"name": {"type": "string"}, "arguments_json": {"type": "string"}},
            },
        },
    },
}

PREAMBLE = (
    "You are the reasoning engine (the LLM) inside a software system. In this role you have NO shell, file, "
    "network or web access: do not run commands, read files or browse. Use only the information in this prompt, "
    "and answer only in the required JSON format."
)


def find_codex_binary(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit if (Path(explicit).exists() or shutil.which(explicit)) else None
    return shutil.which("codex") or next((c for c in _CANDIDATES if Path(c).exists()), None)


def default_model(codex_home: str | None = None) -> str | None:
    """The model configured in the user's ~/.codex/config.toml (used when CODEX_MODEL is unset)."""
    path = Path(codex_home or os.getenv("CODEX_HOME") or Path.home() / ".codex") / "config.toml"
    try:
        return tomllib.loads(path.read_text()).get("model")
    except (OSError, tomllib.TOMLDecodeError):
        return None


def strict_schema(schema: dict) -> dict:
    """OpenAI strict structured-output rules: every object lists all properties as required and forbids
    extra keys; `default` is not allowed. Optional fields stay nullable through their anyOf types."""
    s = copy.deepcopy(schema)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(s)
    return s


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    return str(content)


def render_transcript(messages: Sequence[BaseMessage]) -> tuple[str, str]:
    """(system instructions, conversation transcript)."""
    system, lines = [], []
    for m in messages:
        if isinstance(m, SystemMessage):
            system.append(_content_text(m.content))
        elif isinstance(m, HumanMessage):
            lines.append(f"[USER]\n{_content_text(m.content)}")
        elif isinstance(m, AIMessage):
            text = _content_text(m.content).strip()
            if text:
                lines.append(f"[ASSISTANT]\n{text}")
            for tc in m.tool_calls or []:
                lines.append(f"[ASSISTANT TOOL CALL id={tc.get('id')}] {tc['name']} {json.dumps(tc.get('args', {}), default=str)}")
        elif isinstance(m, ToolMessage):
            lines.append(f"[TOOL RESULT id={m.tool_call_id} name={getattr(m, 'name', '') or ''}]\n{_content_text(m.content)}")
        else:
            lines.append(f"[{m.type.upper()}]\n{_content_text(m.content)}")
    return "\n\n".join(system), "\n\n".join(lines)


def render_tools(tools: list[dict]) -> str:
    out = []
    for t in tools:
        fn = t.get("function", t)
        out.append(f"- {fn['name']}: {fn.get('description', '').strip()}\n  parameters (JSON Schema): {json.dumps(fn.get('parameters', {}))}")
    return "\n".join(out)


def build_prompt(messages: Sequence[BaseMessage], tools: list[dict] | None, tool_choice: Any = None) -> str:
    system, convo = render_transcript(messages)
    parts = [PREAMBLE]
    if system:
        parts.append(f"=== SYSTEM INSTRUCTIONS ===\n{system}")
    if tools:
        parts.append(f"=== TOOLS YOU CAN CALL ===\n{render_tools(tools)}")
    parts.append(f"=== CONVERSATION SO FAR ===\n{convo or '(empty)'}")
    if tools:
        must = ""
        if tool_choice in ("any", "required", True):
            must = " You MUST call at least one tool this turn."
        elif isinstance(tool_choice, str) and tool_choice not in ("auto", "none"):
            must = f" You MUST call the tool '{tool_choice}' this turn."
        parts.append(
            "=== YOUR TURN ===\nWrite the assistant's next message. To call tools, set kind=\"tool_calls\" and list each "
            "call with its exact tool name and \"arguments_json\": a JSON object (as a string) matching that tool's "
            "parameters. Independent calls may be made together in one turn. To answer without tools, set "
            f"kind=\"final\" and put the reply in content (tool_calls empty).{must}"
        )
    else:
        parts.append("=== YOUR TURN ===\nWrite the assistant's next message.")
    return "\n\n".join(parts)


def parse_tool_turn(raw: str, tools: list[dict] | None) -> AIMessage:
    """Codex JSON reply -> AIMessage with tool_calls (unknown tools / bad JSON become invalid_tool_calls)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return AIMessage(content=raw)
    names = {t.get("function", t)["name"] for t in tools or []}
    calls, invalid = [], []
    if data.get("kind") == "tool_calls":
        for tc in data.get("tool_calls") or []:
            call_id = f"call_{uuid.uuid4().hex[:12]}"
            try:
                args = json.loads(tc.get("arguments_json") or "{}")
                if not isinstance(args, dict) or tc.get("name") not in names:
                    raise ValueError("unknown tool or non-object arguments")
                calls.append({"name": tc["name"], "args": args, "id": call_id, "type": "tool_call"})
            except (json.JSONDecodeError, ValueError) as err:
                invalid.append({"name": tc.get("name"), "args": tc.get("arguments_json"), "id": call_id, "error": str(err), "type": "invalid_tool_call"})
    return AIMessage(content=data.get("content") or "", tool_calls=calls, invalid_tool_calls=invalid)


class CodexError(RuntimeError):
    pass


class CodexUsageLimitError(CodexError):
    """The user's Codex plan is out of usage; retrying won't help until it resets."""


class ChatCodexCLI(BaseChatModel):
    """Chat model that runs every completion through the local `codex exec`."""

    model: str | None = Field(default=None, description="Codex model; defaults to the one in ~/.codex/config.toml")
    reasoning_effort: str = "low"
    binary: str | None = None
    timeout_s: float = 180.0
    max_concurrency: int = 4
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _sem: asyncio.Semaphore | None = PrivateAttr(default=None)

    @property
    def _llm_type(self) -> str:
        return "codex-cli"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "reasoning_effort": self.reasoning_effort}

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> dict:
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = "codex"  # deepagents resolves its harness profile from this
        params["ls_model_name"] = self.model or "codex-default"
        return params

    # ---------------------------------------------------------------- LangChain integration

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any) -> Runnable[LanguageModelInput, BaseMessage]:
        formatted = [convert_to_openai_tool(t) for t in tools]
        return self.bind(tools=formatted, tool_choice=tool_choice, **kwargs)

    def with_structured_output(self, schema: Any, *, include_raw: bool = False, method: str | None = None, **kwargs: Any) -> Runnable:  # noqa: ARG002
        is_model = isinstance(schema, type) and issubclass(schema, BaseModel)
        json_schema = strict_schema(schema.model_json_schema() if is_model else schema)

        def to_messages(inp: LanguageModelInput) -> list[BaseMessage]:
            if isinstance(inp, str):
                return [HumanMessage(content=inp)]
            if hasattr(inp, "to_messages"):
                return inp.to_messages()
            return list(inp)

        def finish(raw: str) -> Any:
            data = json.loads(raw)
            parsed = schema.model_validate(data) if is_model else data
            return {"raw": AIMessage(content=raw), "parsed": parsed, "parsing_error": None} if include_raw else parsed

        def run_sync(inp: LanguageModelInput) -> Any:
            return finish(self._call_sync(build_prompt(to_messages(inp), None) + "\nReturn JSON matching the required schema.", json_schema))

        async def run_async(inp: LanguageModelInput) -> Any:
            return finish(await self._call_async(build_prompt(to_messages(inp), None) + "\nReturn JSON matching the required schema.", json_schema))

        return RunnableLambda(run_sync, afunc=run_async)

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        tools = kwargs.get("tools")
        prompt = build_prompt(messages, tools, kwargs.get("tool_choice"))
        raw = self._call_sync(prompt, TOOL_TURN_SCHEMA if tools else None)
        return ChatResult(generations=[ChatGeneration(message=parse_tool_turn(raw, tools) if tools else AIMessage(content=raw))])

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: AsyncCallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        tools = kwargs.get("tools")
        prompt = build_prompt(messages, tools, kwargs.get("tool_choice"))
        raw = await self._call_async(prompt, TOOL_TURN_SCHEMA if tools else None)
        return ChatResult(generations=[ChatGeneration(message=parse_tool_turn(raw, tools) if tools else AIMessage(content=raw))])

    # ---------------------------------------------------------------- codex exec

    def _command(self, workdir: str, schema_path: str | None, out_path: str) -> list[str]:
        binary = find_codex_binary(self.binary)
        if not binary:
            raise CodexError("Codex CLI not found. Install Codex (or the ChatGPT desktop app) and run `codex login`, or set CODEX_BIN.")
        cmd = [
            binary, "exec", "-",
            "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "read-only",
            "--ignore-user-config", "--ignore-rules",
            "--color", "never",
            "-C", workdir,
            "-c", f'model_reasoning_effort="{self.reasoning_effort}"',
            "-o", out_path,
        ]
        model = self.model or default_model()
        if model:
            cmd += ["-m", model]
        if schema_path:
            cmd += ["--output-schema", schema_path]
        return cmd

    def _prepare(self, schema: dict | None) -> tuple[tempfile.TemporaryDirectory, str | None, str]:
        tmp = tempfile.TemporaryDirectory(prefix="codex-llm-")
        schema_path = None
        if schema is not None:
            schema_path = os.path.join(tmp.name, "schema.json")
            Path(schema_path).write_text(json.dumps(schema))
        work = os.path.join(tmp.name, "work")
        os.mkdir(work)  # empty workspace: nothing for the agent to read even if it tried
        return tmp, schema_path, work

    @staticmethod
    def _result(tmp: tempfile.TemporaryDirectory, rc: int, stderr: str) -> str:
        out = Path(tmp.name, "out.txt")
        text = out.read_text().strip() if out.exists() else ""
        if rc != 0 or not text:
            lines = [line for line in stderr.splitlines() if "WebSocket" not in line]
            limit = next((line for line in lines if "usage limit" in line.lower()), None)
            if limit:
                raise CodexUsageLimitError("Codex usage limit reached: " + limit.split("ERROR:", 1)[-1].strip())
            tail = "\n".join(lines)[-600:]
            raise CodexError(f"codex exec failed (exit {rc}): {tail or 'no output'}")
        return text

    def _call_sync(self, prompt: str, schema: dict | None) -> str:
        tmp, schema_path, work = self._prepare(schema)
        try:
            proc = subprocess.run(self._command(work, schema_path, os.path.join(tmp.name, "out.txt")), input=prompt, capture_output=True, text=True, timeout=self.timeout_s)
            return self._result(tmp, proc.returncode, proc.stderr)
        except subprocess.TimeoutExpired as err:
            raise CodexError(f"codex exec timed out after {self.timeout_s:.0f}s") from err
        finally:
            tmp.cleanup()

    async def _call_async(self, prompt: str, schema: dict | None) -> str:
        if self._sem is None:
            self._sem = _shared_semaphore(self.max_concurrency)
        async with self._sem:
            tmp, schema_path, work = self._prepare(schema)
            try:
                proc = await asyncio.create_subprocess_exec(
                    *self._command(work, schema_path, os.path.join(tmp.name, "out.txt")),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                try:
                    _, stderr = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout=self.timeout_s)
                except asyncio.TimeoutError as err:
                    proc.kill()
                    await proc.wait()
                    raise CodexError(f"codex exec timed out after {self.timeout_s:.0f}s") from err
                return self._result(tmp, proc.returncode or 0, stderr.decode(errors="replace"))
            finally:
                tmp.cleanup()


_semaphores: dict[tuple[int, int], asyncio.Semaphore] = {}


def _shared_semaphore(limit: int) -> asyncio.Semaphore:
    """One concurrency limit per event loop, shared by every model instance (avoids rate limits)."""
    key = (id(asyncio.get_running_loop()), limit)
    if key not in _semaphores:
        _semaphores[key] = asyncio.Semaphore(limit)
    return _semaphores[key]


async def codex_status(binary: str | None, model: str | None) -> dict:
    """Health check: binary present and logged in (no model call, so it is instant and free)."""
    path = find_codex_binary(binary)
    resolved = model or default_model()
    if not path:
        return {"ok": False, "provider": "codex", "model": resolved, "error": "Codex CLI not found (install Codex / ChatGPT app or set CODEX_BIN)"}
    auth = Path(os.getenv("CODEX_HOME") or Path.home() / ".codex") / "auth.json"
    if not auth.exists():
        return {"ok": False, "provider": "codex", "model": resolved, "error": "Not logged in: run `codex login`"}
    # `login status` loads config.toml, which may reference host-only paths (plugins, MCP servers). Check the
    # login against a temporary CODEX_HOME that contains only a link to auth.json.
    with tempfile.TemporaryDirectory(prefix="codex-status-") as home:
        os.symlink(auth, os.path.join(home, "auth.json"))
        try:
            proc = await asyncio.create_subprocess_exec(
                path, "login", "status", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                env={**os.environ, "CODEX_HOME": home},
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            text = out.decode(errors="replace").strip()
        except (OSError, asyncio.TimeoutError) as err:
            return {"ok": False, "provider": "codex", "model": resolved, "error": f"Could not run codex: {err}"}
    ok = proc.returncode == 0 and "logged in" in text.lower() and "not logged in" not in text.lower()
    return {"ok": ok, "provider": "codex", "model": resolved, "error": None if ok else (text or "Not logged in: run `codex login`")}
