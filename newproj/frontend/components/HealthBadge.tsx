"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Health } from "@/lib/api-types";

/** Small status dots: backend reachability, Ollama, Vexcel mode. */
export default function HealthBadge() {
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .health()
        .then((h) => {
          if (!cancelled) {
            setHealth(h);
            setDown(false);
          }
        })
        .catch(() => {
          if (!cancelled) setDown(true);
        });
    load();
    const t = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const dot = (ok: boolean | null, warn = false) => (
    <i className={`inline-block h-1.5 w-1.5 rounded-full ${ok == null ? "bg-slate-600" : ok ? (warn ? "bg-amber-400" : "bg-emerald-400") : "bg-rose-400"}`} />
  );

  if (down)
    return (
      <span className="flex items-center gap-1.5 text-[10px] text-rose-300" title="Start the FastAPI backend (see README)">
        {dot(false)} Backend offline
      </span>
    );
  return (
    <span className="flex items-center gap-2.5 text-[10px] text-slate-400">
      <span className="flex items-center gap-1" title={health?.ollama.error ?? health?.ollama.model}>
        {dot(health ? health.ollama.ok : null)} Ollama{health?.ollama.model ? ` · ${health.ollama.model}` : ""}
      </span>
      <span className="flex items-center gap-1">
        {dot(health ? true : null, health?.vexcel === "demo")} Vexcel {health?.vexcel ?? ""}
      </span>
    </span>
  );
}

export function Brand() {
  return (
    <span className="flex items-center gap-2">
      <span className="grid h-7 w-7 place-items-center rounded-lg bg-gradient-to-br from-teal-400 to-cyan-500 text-sm font-black text-ink-950">T</span>
      <span className="leading-tight">
        <span className="block text-sm font-semibold text-slate-100">Turnkey Matchmaker</span>
        <span className="block text-[10px] text-slate-500">Find the right building for your business</span>
      </span>
    </span>
  );
}
