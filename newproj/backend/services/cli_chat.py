"""Shared machinery for LangChain chat models backed by a local CLI (Codex, Claude Code).

Messages are rendered into one transcript prompt. Tool calling: CLIs have no API for caller-defined
tools, so bound tools are described in the prompt and the CLI must answer through a strict JSON schema
{kind, content, tool_calls[]}; the reply becomes a normal AIMessage with `tool_calls`, so Deep Agents /
LangGraph execute tools exactly as with any provider. Structured output passes the (strictified) Pydantic
JSON Schema to the CLI. Subclasses only implement how to build the command and read its answer.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, ClassVar, Sequence

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ConfigDict, PrivateAttr

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


class LLMProviderError(RuntimeError):
    """A provider call failed (bad output, crash, timeout). The next provider may succeed."""


class ProviderExhaustedError(LLMProviderError):
    """The provider can't serve requests for a while (usage limit, not installed, not logged in)."""


def strict_schema(schema: dict) -> dict:
    """OpenAI-style strict structured output: every object lists all properties as required and forbids
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
    """CLI JSON reply -> AIMessage with tool_calls (unknown tools / bad JSON become invalid_tool_calls)."""
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


_semaphores: dict[tuple[int, str, int], asyncio.Semaphore] = {}


def _shared_semaphore(provider: str, limit: int) -> asyncio.Semaphore:
    """One concurrency limit per provider per event loop, shared by every model instance."""
    key = (id(asyncio.get_running_loop()), provider, limit)
    if key not in _semaphores:
        _semaphores[key] = asyncio.Semaphore(limit)
    return _semaphores[key]


class CLIChatModel(BaseChatModel):
    """Base chat model that runs each completion as a one-shot CLI process."""

    provider_name: ClassVar[str] = "cli"
    model: str | None = None
    binary: str | None = None
    timeout_s: float = 180.0
    max_concurrency: int = 4
    model_config = ConfigDict(arbitrary_types_allowed=True)
    _sem: asyncio.Semaphore | None = PrivateAttr(default=None)

    # ---- subclass hooks
    def _command(self, workdir: str, schema: dict | None, schema_path: str | None, out_path: str) -> list[str]:
        raise NotImplementedError

    def _extract(self, rc: int, stdout: str, stderr: str, out_path: str, schema: dict | None) -> str:
        raise NotImplementedError

    # ---- LangChain integration
    @property
    def _llm_type(self) -> str:
        return f"{self.provider_name}-cli"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model}

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> dict:
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = self.provider_name  # deepagents resolves its harness profile from this
        params["ls_model_name"] = self.model or f"{self.provider_name}-default"
        return params

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any) -> Runnable[LanguageModelInput, BaseMessage]:
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], tool_choice=tool_choice, **kwargs)

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

        def prompt_for(inp: LanguageModelInput) -> str:
            return build_prompt(to_messages(inp), None) + "\nReturn JSON matching the required schema."

        def run_sync(inp: LanguageModelInput) -> Any:
            return finish(self._call_sync(prompt_for(inp), json_schema))

        async def run_async(inp: LanguageModelInput) -> Any:
            return finish(await self._call_async(prompt_for(inp), json_schema))

        return RunnableLambda(run_sync, afunc=run_async)

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        tools = kwargs.get("tools")
        raw = self._call_sync(build_prompt(messages, tools, kwargs.get("tool_choice")), TOOL_TURN_SCHEMA if tools else None)
        return ChatResult(generations=[ChatGeneration(message=parse_tool_turn(raw, tools) if tools else AIMessage(content=raw))])

    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: AsyncCallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        tools = kwargs.get("tools")
        raw = await self._call_async(build_prompt(messages, tools, kwargs.get("tool_choice")), TOOL_TURN_SCHEMA if tools else None)
        return ChatResult(generations=[ChatGeneration(message=parse_tool_turn(raw, tools) if tools else AIMessage(content=raw))])

    # ---- process plumbing
    def _prepare(self, schema: dict | None) -> tuple[tempfile.TemporaryDirectory, str | None, str, str]:
        tmp = tempfile.TemporaryDirectory(prefix=f"{self.provider_name}-llm-")
        schema_path = None
        if schema is not None:
            schema_path = os.path.join(tmp.name, "schema.json")
            Path(schema_path).write_text(json.dumps(schema))
        work = os.path.join(tmp.name, "work")
        os.mkdir(work)  # empty workspace: nothing for the CLI to read even if it tried
        return tmp, schema_path, work, os.path.join(tmp.name, "out.txt")

    def _call_sync(self, prompt: str, schema: dict | None) -> str:
        tmp, schema_path, work, out = self._prepare(schema)
        try:
            proc = subprocess.run(self._command(work, schema, schema_path, out), input=prompt, capture_output=True, text=True, timeout=self.timeout_s, cwd=work)
            return self._extract(proc.returncode, proc.stdout, proc.stderr, out, schema)
        except subprocess.TimeoutExpired as err:
            raise LLMProviderError(f"{self.provider_name} timed out after {self.timeout_s:.0f}s") from err
        finally:
            tmp.cleanup()

    async def _call_async(self, prompt: str, schema: dict | None) -> str:
        if self._sem is None:
            self._sem = _shared_semaphore(self.provider_name, self.max_concurrency)
        async with self._sem:
            tmp, schema_path, work, out = self._prepare(schema)
            try:
                proc = await asyncio.create_subprocess_exec(
                    *self._command(work, schema, schema_path, out),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=work,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(prompt.encode()), timeout=self.timeout_s)
                except asyncio.TimeoutError as err:
                    proc.kill()
                    await proc.wait()
                    raise LLMProviderError(f"{self.provider_name} timed out after {self.timeout_s:.0f}s") from err
                return self._extract(proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace"), out, schema)
            finally:
                tmp.cleanup()
