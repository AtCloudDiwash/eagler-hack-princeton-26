"use client";

import { api } from "@/lib/api";
import { isLocalLlm } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

/**
 * Header pill showing whether the backend is reachable, whether it serves mock or live data, and
 * "Local AI ready" when the summary LLM runs on Ollama.
 */
export function ApiStatus() {
  const health = useAsync((signal) => api.health({ signal }), "health");

  if (health.status === "loading") return null;
  if (health.status === "error") {
    return (
      <span className="flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line px-2 py-0.5 text-xs text-ink-muted" title="Backend not reachable">
        <span className="size-1.5 rounded-full bg-risk" aria-hidden />
        API offline
      </span>
    );
  }
  // Only the data providers decide mock/live; parser and llm are reported separately.
  const modes = Object.entries(health.data.mode ?? {})
    .filter(([name]) => name !== "parser" && name !== "llm")
    .map(([, value]) => value);
  const live = modes.includes("live");
  const allLive = modes.length > 0 && modes.every((mode) => mode === "live");
  const label = allLive ? "live data" : live ? "mixed data" : "mock data";
  const localAi = isLocalLlm(health.data.mode?.llm);
  const detail = Object.entries(health.data.mode ?? {})
    .map(([name, mode]) => `${name}: ${mode}`)
    .join(", ");
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line px-2 py-0.5 text-xs text-ink-muted" title={detail}>
      <span className="size-1.5 rounded-full bg-pass" aria-hidden />
      <span className="hidden sm:inline">API ·</span> {label}
      {localAi && (
        <span className="hidden text-accent md:inline" data-testid="local-ai-ready">
          · Local AI ready
        </span>
      )}
    </span>
  );
}
