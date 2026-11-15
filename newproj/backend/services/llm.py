"""LLM access with an ordered fallback chain: Codex CLI → Claude Code CLI → Ollama (LLM_PROVIDERS).

`chat_model()` returns a FallbackChat: a regular LangChain chat model (tool calling + structured output)
that tries each configured provider in order. A provider that is exhausted (usage limit, not installed,
not logged in) is skipped for LLM_COOLDOWN_S so later calls don't wait on it; any other error falls
through to the next provider for that call only. Each analysis records which provider served how many
calls (`track_usage`), and switches are reported through an event callback (`on_fallback`).
"""
from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any, Callable, Sequence

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_tool

from config import settings
from services.claude_chat import ChatClaudeCLI, claude_status
from services.cli_chat import LLMProviderError, ProviderExhaustedError
from services.codex_chat import ChatCodexCLI, codex_status, default_model

LABELS = {"codex": "Codex CLI", "claude": "Claude Code", "ollama": "Ollama"}

# provider -> (unavailable until epoch seconds, reason)
_unavailable: dict[str, tuple[float, str]] = {}
# Per-analysis bookkeeping (set by the engine; context vars follow asyncio tasks).
_usage: ContextVar[dict[str, int] | None] = ContextVar("llm_usage", default=None)
_on_fallback: ContextVar[Callable[[str], None] | None] = ContextVar("llm_on_fallback", default=None)


class AllProvidersFailedError(LLMProviderError):
    """Every configured provider failed for this call.

    `exhausted` is True only when every provider is now marked unavailable (usage limit, not installed,
    not logged in): retrying is pointless and the analysis should stop. Otherwise the failure was specific
    to this call (bad JSON, a timeout) and only the calling agent should fail.
    """

    def __init__(self, message: str, exhausted: bool = False) -> None:
        super().__init__(message)
        self.exhausted = exhausted


def track_usage() -> dict[str, int]:
    """Start counting provider calls for the current analysis; returns the live counter dict."""
    counts: dict[str, int] = {}
    _usage.set(counts)
    return counts


def on_fallback(callback: Callable[[str], None]) -> None:
    _on_fallback.set(callback)


def model_label(name: str) -> str:
    model = {"codex": settings.codex_model or default_model(), "claude": settings.claude_model, "ollama": settings.ollama_model}.get(name)
    return f"{LABELS.get(name, name)} ({model})" if model else LABELS.get(name, name)


def _make(name: str, reasoning_effort: str | None) -> BaseChatModel:
    if name == "codex":
        return ChatCodexCLI(model=settings.codex_model, reasoning_effort=reasoning_effort or settings.codex_reasoning_effort,
                            binary=settings.codex_bin, timeout_s=settings.codex_timeout_s, max_concurrency=settings.codex_max_concurrency)
    if name == "claude":
        return ChatClaudeCLI(model=settings.claude_model, binary=settings.claude_bin, timeout_s=settings.claude_timeout_s,
                             max_concurrency=settings.claude_max_concurrency)
    if name == "ollama":
        from langchain_ollama import ChatOllama  # imported lazily: only needed when Ollama is reached

        return ChatOllama(model=settings.ollama_model, base_url=settings.ollama_base_url, temperature=0, reasoning=False, num_ctx=16384)
    raise ValueError(f"Unknown LLM provider '{name}' (use codex, claude or ollama)")


def _available(name: str) -> tuple[bool, str]:
    until, reason = _unavailable.get(name, (0.0, ""))
    if until > time.time():
        return False, reason
    _unavailable.pop(name, None)
    return True, ""


def _mark_exhausted(name: str, reason: str) -> None:
    _unavailable[name] = (time.time() + settings.llm_cooldown_s, reason)


def reset_cooldowns() -> None:
    _unavailable.clear()


class FallbackChat(BaseChatModel):
    """Chat model that delegates to the first provider in `providers` that succeeds."""

    providers: list[str]
    reasoning_effort: str | None = None

    @property
    def _llm_type(self) -> str:
        return "turnkey-fallback"

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> dict:
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = "turnkey"  # one stable key for the Deep Agents harness profile
        params["ls_model_name"] = "+".join(self.providers)
        return params

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: Any = None, **kwargs: Any) -> Runnable[LanguageModelInput, BaseMessage]:
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], tool_choice=tool_choice, **kwargs)

    # ---- provider loop
    def _next_available(self, after: int) -> str | None:
        return next((n for n in self.providers[after + 1:] if _available(n)[0]), None)

    def _all_unavailable(self) -> bool:
        return not any(_available(n)[0] for n in self.providers)

    def _note(self, name: str, reason: str, nxt: str | None) -> None:
        cb = _on_fallback.get()
        if cb and nxt:
            cb(f"{LABELS.get(name, name)} unavailable ({reason[:140]}); switching to {LABELS.get(nxt, nxt)}")

    def _record(self, name: str) -> None:
        usage = _usage.get()
        if usage is not None:
            usage[name] = usage.get(name, 0) + 1

    async def _try_async(self, call: Callable[[BaseChatModel], Any]) -> Any:
        errors: list[str] = []
        for i, name in enumerate(self.providers):
            ok, reason = _available(name)
            if not ok:
                errors.append(f"{name}: {reason}")
                continue
            try:
                result = await call(_make(name, self.reasoning_effort))
            except ProviderExhaustedError as err:
                _mark_exhausted(name, str(err))
                errors.append(f"{name}: {err}")
                self._note(name, str(err), self._next_available(i))
                continue
            except Exception as err:  # noqa: BLE001 - any provider failure falls through to the next one
                errors.append(f"{name}: {err}")
                self._note(name, str(err), self._next_available(i))
                continue
            self._record(name)
            return result
        raise AllProvidersFailedError("All LLM providers failed — " + " | ".join(errors), exhausted=self._all_unavailable())

    def _try_sync(self, call: Callable[[BaseChatModel], Any]) -> Any:
        errors: list[str] = []
        for name in self.providers:
            ok, reason = _available(name)
            if not ok:
                errors.append(f"{name}: {reason}")
                continue
            try:
                result = call(_make(name, self.reasoning_effort))
            except ProviderExhaustedError as err:
                _mark_exhausted(name, str(err))
                errors.append(f"{name}: {err}")
                continue
            except Exception as err:  # noqa: BLE001 - any provider failure falls through to the next one
                errors.append(f"{name}: {err}")
                continue
            self._record(name)
            return result
        raise AllProvidersFailedError("All LLM providers failed — " + " | ".join(errors), exhausted=self._all_unavailable())

    # ---- LangChain API
    async def _agenerate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: AsyncCallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        tools, choice = kwargs.get("tools"), kwargs.get("tool_choice")

        async def call(model: BaseChatModel) -> BaseMessage:
            runnable = model.bind_tools(tools, tool_choice=choice) if tools else model
            return await runnable.ainvoke(messages)

        return ChatResult(generations=[ChatGeneration(message=await self._try_async(call))])

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: CallbackManagerForLLMRun | None = None, **kwargs: Any) -> ChatResult:
        tools, choice = kwargs.get("tools"), kwargs.get("tool_choice")

        def call(model: BaseChatModel) -> BaseMessage:
            runnable = model.bind_tools(tools, tool_choice=choice) if tools else model
            return runnable.invoke(messages)

        return ChatResult(generations=[ChatGeneration(message=self._try_sync(call))])

    def with_structured_output(self, schema: Any, *, include_raw: bool = False, method: str | None = None, **kwargs: Any) -> Runnable:  # noqa: ARG002
        def normalize(inp: LanguageModelInput) -> Any:
            return [HumanMessage(content=inp)] if isinstance(inp, str) else inp

        def run_sync(inp: LanguageModelInput) -> Any:
            return self._try_sync(lambda m: m.with_structured_output(schema, method="json_schema", include_raw=include_raw).invoke(normalize(inp)))

        async def run_async(inp: LanguageModelInput) -> Any:
            return await self._try_async(lambda m: m.with_structured_output(schema, method="json_schema", include_raw=include_raw).ainvoke(normalize(inp)))

        return RunnableLambda(run_sync, afunc=run_async)


def chat_model(reasoning_effort: str | None = None) -> FallbackChat:
    return FallbackChat(providers=settings.llm_providers, reasoning_effort=reasoning_effort)


async def _ollama_status() -> dict:
    base = {"provider": "ollama", "label": "Ollama", "model": settings.ollama_model}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            res = await client.get(f"{settings.ollama_base_url}/api/tags")
        names = [m["name"] for m in res.json().get("models", [])]
    except (httpx.HTTPError, ValueError) as err:
        return {**base, "ok": False, "error": f"Ollama not reachable at {settings.ollama_base_url}: {err}"}
    ok = settings.ollama_model in names
    return {**base, "ok": ok, "error": None if ok else f"Model {settings.ollama_model} not pulled (ollama pull {settings.ollama_model})"}


async def llm_status() -> dict:
    """`llm` = the provider analyses will use first (backwards compatible fields), plus every provider's status."""
    checks = {"codex": lambda: codex_status(settings.codex_bin, settings.codex_model),
              "claude": lambda: claude_status(settings.claude_bin, settings.claude_model),
              "ollama": _ollama_status}
    providers = []
    for name in settings.llm_providers:
        if name not in checks:
            continue
        status = await checks[name]()
        ok, reason = _available(name)
        if status["ok"] and not ok:
            status = {**status, "ok": False, "error": reason, "cooling_down": True}
        providers.append(status)
    active = next((p for p in providers if p["ok"]), None)
    lead = active or (providers[0] if providers else {"provider": "none", "label": "No LLM", "model": None, "error": "LLM_PROVIDERS is empty"})
    return {
        "ok": active is not None,
        "provider": lead["provider"],
        "label": lead.get("label"),
        "model": lead.get("model"),
        "error": None if active else ("; ".join(f"{p['provider']}: {p['error']}" for p in providers) or lead.get("error")),
        "providers": providers,
    }
