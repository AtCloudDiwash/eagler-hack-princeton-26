"""LLM access. All inference runs through the local Codex CLI (services/codex_chat.py) using the
user's own Codex / ChatGPT login; no API key is stored in this app."""
from __future__ import annotations

from config import settings
from services.codex_chat import ChatCodexCLI, codex_status


def chat_model(reasoning_effort: str | None = None) -> ChatCodexCLI:
    return ChatCodexCLI(
        model=settings.codex_model,
        reasoning_effort=reasoning_effort or settings.codex_reasoning_effort,
        binary=settings.codex_bin,
        timeout_s=settings.codex_timeout_s,
        max_concurrency=settings.codex_max_concurrency,
    )


async def llm_status() -> dict:
    return await codex_status(settings.codex_bin, settings.codex_model)
