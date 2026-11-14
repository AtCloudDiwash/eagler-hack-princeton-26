"""Small LLM provider abstraction: schema-constrained JSON from Ollama (local) or Anthropic.

`LLM_PROVIDER` selects the provider:

* ``ollama`` (default) — a local model served by Ollama (`OLLAMA_BASE_URL`, `OLLAMA_MODEL`), called
  with plain httpx: ``POST /api/chat`` with ``stream: false``, a JSON-schema ``format`` (structured
  outputs), ``temperature: 0`` and ``think: false`` (qwen3's reasoning trace is disabled; any stray
  ``<think>`` block is stripped anyway).
* ``anthropic`` — Claude via the Anthropic SDK; needs `ANTHROPIC_API_KEY`.
* ``none`` — no LLM; the regex parser runs and `ai_summary` is null.

The LLM only extracts requirement fields and explains an already-computed ranking. It never
computes costs, scores, statuses or ranks (those stay deterministic). Every caller treats
`LLMError` (or any exception) as "no LLM" and falls back.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any

import httpx

from ..config import log, settings

AVAILABILITY_TTL_SECONDS = 30.0
AVAILABILITY_TIMEOUT_SECONDS = 1.5
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

# (checked_at monotonic seconds, available) for the Ollama /api/tags probe.
_availability: tuple[float, bool] | None = None
_lock = threading.Lock()


class LLMError(RuntimeError):
    """Any LLM failure: unreachable, timeout, bad status, truncated output or invalid JSON."""


# --------------------------------------------------------------------------------------------
# Provider info
# --------------------------------------------------------------------------------------------


def provider() -> str:
    """'ollama' | 'anthropic' | 'none' (unknown values are treated as 'none')."""
    value = settings.llm_provider
    return value if value in {"ollama", "anthropic"} else "none"


def label() -> str:
    """Configured model label, e.g. 'ollama:qwen3:8b', 'anthropic:claude-haiku-5-5', 'none'."""
    name = provider()
    if name == "ollama":
        return f"ollama:{settings.ollama_model}"
    if name == "anthropic":
        return f"anthropic:{settings.anthropic_model}"
    return "none"


def parser_name() -> str:
    """Value reported in `mode.parser` when the configured LLM parsed the requirements."""
    return {"ollama": "ollama", "anthropic": "claude"}.get(provider(), "regex")


def _model_listed(tags: dict[str, Any], model: str) -> bool:
    names = {m.get("name") for m in tags.get("models", [])} | {m.get("model") for m in tags.get("models", [])}
    return model in names or (":" not in model and f"{model}:latest" in names)


def _set_availability(available: bool) -> None:
    global _availability
    with _lock:
        _availability = (time.monotonic(), available)


def reset_availability_cache() -> None:
    global _availability
    with _lock:
        _availability = None


def is_available() -> bool:
    """Cheap check that the configured LLM can be called.

    Ollama: GET /api/tags (short timeout) and the configured model is pulled; cached ~30 s.
    Anthropic: an API key is set. None: False."""
    name = provider()
    if name == "anthropic":
        return bool(settings.anthropic_api_key)
    if name != "ollama":
        return False
    with _lock:
        cached = _availability
    if cached and time.monotonic() - cached[0] < AVAILABILITY_TTL_SECONDS:
        return cached[1]
    try:
        response = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=AVAILABILITY_TIMEOUT_SECONDS)
        response.raise_for_status()
        available = _model_listed(response.json(), settings.ollama_model)
        if not available:
            log.warning("Ollama is up but model %s is not pulled (ollama pull %s)", settings.ollama_model, settings.ollama_model)
    except Exception as exc:  # noqa: BLE001 - unreachable / bad response = unavailable
        log.info("Ollama not reachable at %s (%s)", settings.ollama_base_url, type(exc).__name__)
        available = False
    _set_availability(available)
    return available


# --------------------------------------------------------------------------------------------
# Calls
# --------------------------------------------------------------------------------------------


def strip_think(text: str) -> str:
    """Remove <think>...</think> reasoning blocks (and an unterminated leading one)."""
    text = _THINK_RE.sub("", text)
    if "<think>" in text.lower():
        text = text[: text.lower().index("<think>")]
    return text.strip()


def _parse_json(text: str) -> dict[str, Any]:
    text = strip_think(text)
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"invalid JSON from model: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("model output is not a JSON object")
    return data


def _ollama_chat(system: str, user: str, schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    body = {
        "model": settings.ollama_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "format": schema,
        "think": False,
        "keep_alive": settings.ollama_keep_alive,
        "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": settings.ollama_num_ctx},
    }
    try:
        response = httpx.post(f"{settings.ollama_base_url}/api/chat", json=body, timeout=settings.llm_timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        _set_availability(False)  # don't make the next call wait for the same timeout
        raise LLMError(f"Ollama unreachable or timed out: {type(exc).__name__}") from exc
    except (httpx.HTTPStatusError, ValueError) as exc:
        raise LLMError(f"Ollama error: {exc}") from exc
    if payload.get("done_reason") == "length":
        raise LLMError("Ollama output truncated (num_predict reached)")
    return _parse_json((payload.get("message") or {}).get("content") or "")


def _anthropic_client():
    """Build the SDK client. Separate function so tests can replace it with a fake."""
    import anthropic

    return anthropic.Anthropic(
        api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds, max_retries=0
    )


def _anthropic_chat(system: str, user: str, schema: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY is not set")
    response = _anthropic_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=max(max_tokens, 2048),
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
    )
    if response.stop_reason != "end_turn":
        raise LLMError(f"Claude stopped with stop_reason={response.stop_reason}")
    text = next(block.text for block in response.content if block.type == "text")
    return _parse_json(text)


def chat_json(system: str, user: str, schema: dict[str, Any], *, max_tokens: int = 512, purpose: str = "llm") -> dict[str, Any]:
    """One schema-constrained JSON call to the configured provider. Raises LLMError on any failure."""
    name = provider()
    if name == "none":
        raise LLMError("LLM_PROVIDER=none")
    started = time.perf_counter()
    try:
        if name == "ollama":
            return _ollama_chat(system, user, schema, max_tokens)
        return _anthropic_chat(system, user, schema, max_tokens)
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize SDK errors
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        log.info("LLM %s via %s took %.2fs", purpose, label(), time.perf_counter() - started)


def warm_up() -> None:
    """Load the Ollama model into memory in the background so the first analysis isn't slow.

    An empty /api/generate request with keep_alive loads the model and returns. No-op for other
    providers or when Ollama isn't reachable."""
    if provider() != "ollama":
        return

    def _load() -> None:
        if not is_available():
            return
        started = time.perf_counter()
        try:
            httpx.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": settings.ollama_model, "keep_alive": settings.ollama_keep_alive,
                      "options": {"num_ctx": settings.ollama_num_ctx}},
                timeout=max(settings.llm_timeout_seconds, 60),
            ).raise_for_status()
            log.info("Ollama model %s loaded in %.1fs", settings.ollama_model, time.perf_counter() - started)
        except Exception as exc:  # noqa: BLE001
            log.warning("Ollama warm-up failed (%s)", type(exc).__name__)

    threading.Thread(target=_load, name="ollama-warm-up", daemon=True).start()
