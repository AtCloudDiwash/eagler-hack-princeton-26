"""Claude Code CLI chat model (`claude -p`), using the user's own Claude login (fallback after Codex).

Each call: print mode, JSON output, `--json-schema` forcing the answer shape, all tools disabled
(`--tools ""`), no MCP servers, no session persistence, an empty temp folder as the working directory and
a minimal system prompt. Prompt rendering, tool calling and structured output live in services/cli_chat.py.
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import ClassVar

from services.cli_chat import PREAMBLE, CLIChatModel, LLMProviderError, ProviderExhaustedError

_CANDIDATES = [str(Path.home() / ".local/bin/claude"), "/usr/local/bin/claude", "/opt/homebrew/bin/claude"]
# Claude Code answers --json-schema through its own internal tool, and with our tools listed in the prompt it
# sometimes tries to call them natively ("No such tool available") and then gives up. Spell out the contract.
TOOL_CONTRACT = (
    " The tools listed under 'TOOLS YOU CAN CALL' are NOT available to you as native tools and you must never try "
    "to invoke them directly. To use one, return JSON with kind=\"tool_calls\" listing the calls; the system runs "
    "them and shows you the results in the next turn. A tool is never 'unavailable' just because you cannot call it natively."
)
_LIMIT_WORDS = ("usage limit", "rate limit", "rate_limit", "quota", "overloaded", "credit balance", "limit reached")


class NativeToolAttemptError(LLMProviderError):
    """Claude tried to call a listed tool natively instead of returning kind=tool_calls; the reply is unusable."""


RETRY_NOTE = (
    "\n\n(Reminder: you cannot call the listed tools yourself. If you need one, answer with kind=\"tool_calls\" "
    "and the system will run it.)"
)


class ClaudeUsageLimitError(ProviderExhaustedError):
    """Claude usage/rate limit reached."""


def find_claude_binary(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit if (Path(explicit).exists() or shutil.which(explicit)) else None
    return shutil.which("claude") or next((c for c in _CANDIDATES if Path(c).exists()), None)


class ChatClaudeCLI(CLIChatModel):
    """Chat model that runs every completion through the local Claude Code CLI."""

    provider_name: ClassVar[str] = "claude"
    model: str | None = "sonnet"

    def _command(self, workdir: str, schema: dict | None, schema_path: str | None, out_path: str) -> list[str]:
        binary = find_claude_binary(self.binary)
        if not binary:
            raise ProviderExhaustedError("Claude Code CLI not found. Install it and run `claude auth login`, or set CLAUDE_BIN.")
        cmd = [
            binary, "-p",
            "--output-format", "json",
            "--tools", "",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--system-prompt", PREAMBLE + TOOL_CONTRACT,
        ]
        if self.model:
            cmd += ["--model", self.model]
        if schema is not None:
            cmd += ["--json-schema", json.dumps(schema)]
        return cmd

    def _call_sync(self, prompt: str, schema: dict | None) -> str:
        try:
            return super()._call_sync(prompt, schema)
        except NativeToolAttemptError:
            return super()._call_sync(prompt + RETRY_NOTE, schema)  # a second failure falls through to the next provider

    async def _call_async(self, prompt: str, schema: dict | None) -> str:
        try:
            return await super()._call_async(prompt, schema)
        except NativeToolAttemptError:
            return await super()._call_async(prompt + RETRY_NOTE, schema)

    def _extract(self, rc: int, stdout: str, stderr: str, out_path: str, schema: dict | None) -> str:
        try:
            data = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
        except (json.JSONDecodeError, IndexError):
            data = {}
        message = str(data.get("result") or "") + " " + stderr
        if rc != 0 or data.get("is_error") or not data:
            low = message.lower()
            if any(w in low for w in _LIMIT_WORDS) or data.get("api_error_status") in (429, 529):
                raise ClaudeUsageLimitError(f"Claude usage limit: {message.strip()[:200]}")
            if "not logged in" in low or "invalid api key" in low or "/login" in low:
                raise ProviderExhaustedError("Claude Code is not logged in: run `claude auth login`")
            raise LLMProviderError(f"claude -p failed (exit {rc}): {message.strip()[-500:] or 'no output'}")
        if schema is not None:
            structured = data.get("structured_output")
            if structured is None:
                raise LLMProviderError("claude -p returned no structured output")
            if _is_tool_turn(schema) and _tried_native_tools(data, structured):
                raise NativeToolAttemptError("claude tried to call agent tools natively")
            return json.dumps(structured)
        return str(data.get("result") or "")


async def claude_status(binary: str | None, model: str | None) -> dict:
    path = find_claude_binary(binary)
    base = {"provider": "claude", "label": "Claude Code", "model": model or "sonnet"}
    if not path:
        return {**base, "ok": False, "error": "Claude Code CLI not found (set CLAUDE_BIN)"}
    try:
        proc = await asyncio.create_subprocess_exec(path, "auth", "status", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        data = json.loads(out.decode(errors="replace") or "{}")
    except (OSError, asyncio.TimeoutError, json.JSONDecodeError) as err:
        return {**base, "ok": False, "error": f"Could not check Claude login: {err}"}
    ok = bool(data.get("loggedIn"))
    return {**base, "ok": ok, "error": None if ok else "Not logged in: run `claude auth login`"}


def _is_tool_turn(schema: dict) -> bool:
    return "tool_calls" in (schema.get("properties") or {})


def _tried_native_tools(data: dict, structured: dict) -> bool:
    """A clean answer is one turn plus the structured-output turn; extra turns mean failed native tool calls."""
    said_unavailable = "no such tool" in str(structured.get("content") or "").lower()
    return said_unavailable or (structured.get("kind") == "final" and (data.get("num_turns") or 0) > 2)
