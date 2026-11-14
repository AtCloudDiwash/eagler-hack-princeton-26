"""Ollama access (all LLM inference runs locally through Ollama)."""
from __future__ import annotations

import httpx
from langchain_ollama import ChatOllama

from config import settings


def chat_model(temperature: float = 0.0, think: bool | None = None, num_predict: int | None = None) -> ChatOllama:
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=temperature,
        reasoning=settings.ollama_think if think is None else think,
        num_ctx=16384,
        num_predict=num_predict,
    )


async def ollama_status() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            res = await client.get(f"{settings.ollama_base_url}/api/tags")
        names = [m["name"] for m in res.json().get("models", [])]
        ok = settings.ollama_model in names
        return {"ok": ok, "model": settings.ollama_model, "error": None if ok else f"Model {settings.ollama_model} not pulled (ollama pull {settings.ollama_model})"}
    except (httpx.HTTPError, ValueError) as err:
        return {"ok": False, "model": settings.ollama_model, "error": f"Ollama not reachable at {settings.ollama_base_url}: {err}"}
