"""Codex CLI chat model (`codex exec`), using the user's own Codex / ChatGPT login in ~/.codex.

Each call: `codex exec -` ephemeral (no session files), read-only sandbox in an empty temp folder, the
user's personal Codex config/rules ignored (plugins, MCP servers, hooks), `--output-schema` forcing the
JSON shape. Prompt rendering, tool calling and structured output live in services/cli_chat.py.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import ClassVar

from services.cli_chat import (  # noqa: F401  (re-exported for callers/tests)
    PREAMBLE,
    TOOL_TURN_SCHEMA,
    CLIChatModel,
    LLMProviderError,
    ProviderExhaustedError,
    build_prompt,
    parse_tool_turn,
    render_tools,
    render_transcript,
    strict_schema,
)

# Known install locations: PATH, then the CLI bundled inside the ChatGPT / Codex desktop app (macOS).
_CANDIDATES = [
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
    "/Applications/Codex.app/Contents/Resources/codex-cli/bin/codex",
    str(Path.home() / ".codex/plugins/.plugin-appserver/codex-cli/bin/codex"),
]

CodexError = LLMProviderError


class CodexUsageLimitError(ProviderExhaustedError):
    """The user's Codex plan is out of usage; retrying won't help until it resets."""


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


class ChatCodexCLI(CLIChatModel):
    """Chat model that runs every completion through the local `codex exec`."""

    provider_name: ClassVar[str] = "codex"
    reasoning_effort: str = "low"

    def _command(self, workdir: str, schema: dict | None, schema_path: str | None, out_path: str) -> list[str]:
        binary = find_codex_binary(self.binary)
        if not binary:
            raise ProviderExhaustedError("Codex CLI not found. Install Codex (or the ChatGPT desktop app) and run `codex login`, or set CODEX_BIN.")
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

    def _extract(self, rc: int, stdout: str, stderr: str, out_path: str, schema: dict | None) -> str:
        out = Path(out_path)
        text = out.read_text().strip() if out.exists() else ""
        if rc != 0 or not text:
            lines = [line for line in stderr.splitlines() if "WebSocket" not in line]
            limit = next((line for line in lines if "usage limit" in line.lower()), None)
            if limit:
                raise CodexUsageLimitError("Codex usage limit reached: " + limit.split("ERROR:", 1)[-1].strip())
            if any("not logged in" in line.lower() for line in lines):
                raise ProviderExhaustedError("Codex is not logged in: run `codex login`")
            tail = "\n".join(lines)[-600:]
            raise LLMProviderError(f"codex exec failed (exit {rc}): {tail or 'no output'}")
        return text


async def codex_status(binary: str | None, model: str | None) -> dict:
    """Binary present and logged in (no model call, so it is instant and free)."""
    path = find_codex_binary(binary)
    resolved = model or default_model()
    base = {"provider": "codex", "label": "Codex CLI", "model": resolved}
    if not path:
        return {**base, "ok": False, "error": "Codex CLI not found (install Codex / ChatGPT app or set CODEX_BIN)"}
    auth = Path(os.getenv("CODEX_HOME") or Path.home() / ".codex") / "auth.json"
    if not auth.exists():
        return {**base, "ok": False, "error": "Not logged in: run `codex login`"}
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
            return {**base, "ok": False, "error": f"Could not run codex: {err}"}
    ok = proc.returncode == 0 and "logged in" in text.lower() and "not logged in" not in text.lower()
    return {**base, "ok": ok, "error": None if ok else (text or "Not logged in: run `codex login`")}
