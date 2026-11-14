"use client";

import { api } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";

/** Header pill showing whether the backend is reachable and whether it serves mock or live data. */
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
  const modes = Object.values(health.data.mode ?? {});
  const live = modes.includes("live") || modes.includes("claude");
  const allLive = modes.length > 0 && modes.every((mode) => mode === "live" || mode === "claude");
  const label = allLive ? "live data" : live ? "mixed data" : "mock data";
  const detail = Object.entries(health.data.mode ?? {})
    .map(([name, mode]) => `${name}: ${mode}`)
    .join(", ");
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line px-2 py-0.5 text-xs text-ink-muted" title={detail}>
      <span className="size-1.5 rounded-full bg-pass" aria-hidden />
      <span className="hidden sm:inline">API ·</span> {label}
    </span>
  );
}
