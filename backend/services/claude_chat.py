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
_LIMIT_WORDS = ("usage limit", "rate limit", "rate_limit", "quota", "overloaded", "credit balance", "limit reached")


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
            "--system-prompt", PREAMBLE,
        ]
        if self.model:
            cmd += ["--model", self.model]
        if schema is not None:
            cmd += ["--json-schema", json.dumps(schema)]
        return cmd

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
