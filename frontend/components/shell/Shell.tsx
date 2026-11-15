"use client";

import { AnimatePresence, motion } from "motion/react";
import { Box, Check, Layers, Map as MapIcon, Satellite } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Health } from "@/lib/api-types";

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" className="flex items-center gap-2.5" aria-label="EagleEye home">
      {/* eslint-disable-next-line @next/next/no-img-element -- small static mark; no optimization needed */}
      <img src="/brand/eagleeye-mark.png" alt="" width={40} height={20} className="h-5 w-10 object-contain" />
      {!compact && <span className="text-sm font-semibold tracking-tight text-slate-50">EagleEye</span>}
    </Link>
  );
}

/** Status dots: backend, LLM (Codex CLI), Vexcel mode. Details on hover. */
export function HealthDots() {
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .health()
        .then((h) => !cancelled && (setHealth(h), setDown(false)))
        .catch(() => !cancelled && setDown(true));
    load();
    const t = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);
  const dot = (ok: boolean | null, warn = false) => (
    <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${ok == null ? "bg-slate-600" : !ok ? "bg-rose-400" : warn ? "bg-amber-400" : "bg-emerald-400"}`}>
      {ok && !warn && <span className="absolute inset-0 animate-ping rounded-full bg-emerald-400/60" />}
    </span>
  );
  if (down) return <span className="flex items-center gap-1.5 text-[10px] text-rose-300">{dot(false)} Backend offline</span>;
  return (
    <span className="flex items-center gap-3 text-[10px] text-slate-400">
      <span className="flex items-center gap-1.5" title={llmTitle(health)}>
        {/* amber = a fallback is in use (the first provider in the chain is unavailable) */}
        {dot(health ? health.llm.ok : null, !!health?.llm.providers?.length && health.llm.provider !== health.llm.providers[0].provider)}{" "}
        {SHORT_LLM[health?.llm.provider ?? ""] ?? health?.llm.label ?? "LLM"}
      </span>
      <span className="flex items-center gap-1.5" title={`Vexcel ${health?.vexcel ?? ""}`}>
        {dot(health ? true : null, health?.vexcel === "demo")} Vexcel{health?.vexcel === "demo" ? " demo" : ""}
      </span>
    </span>
  );
}

const SHORT_LLM: Record<string, string> = { codex: "Codex", claude: "Claude", ollama: "Ollama" };

/** Tooltip: the whole chain with each provider's state, e.g. "Codex ✕ usage limit · Claude ✓ sonnet · Ollama ✓". */
function llmTitle(health: Health | null): string {
  const chain = health?.llm.providers;
  if (!chain?.length) return health?.llm.error ?? `${health?.llm.label ?? "LLM"}${health?.llm.model ? ` · ${health.llm.model}` : ""}`;
  return "LLM fallback chain:\n" + chain.map((p) => `${p.ok ? "✓" : "✕"} ${p.label}${p.model ? ` (${p.model})` : ""}${p.ok ? "" : ` — ${p.error ?? "unavailable"}`}`).join("\n");
}

export const STEPS = [
  { label: "Describe", hint: "Tell us your business and where" },
  { label: "Pick a building", hint: "Choose one of the matches on the map" },
  { label: "Agents investigate", hint: "AI agents check fit, rules and costs" },
  { label: "Decide", hint: "See the verdict, budget and evidence" },
] as const;

/** Slim 4-step progress: what the user is doing now, in one line. */
export function Stepper({ step, hint = "inline" }: { step: 0 | 1 | 2 | 3; hint?: "inline" | "below" }) {
  const pill = (
    <div className="glass flex items-center gap-1 rounded-full px-2 py-1.5">
      {STEPS.map((s, i) => {
        const done = i < step;
        const on = i === step;
        return (
          <div key={s.label} className="flex items-center">
            {i > 0 && <span className={`mx-1 h-px w-3 sm:w-5 ${i <= step ? "bg-teal-400/60" : "bg-white/10"}`} />}
            <div className="relative flex items-center gap-1.5 rounded-full px-2 py-1">
              {on && <motion.span layoutId="stepper-active" className="absolute inset-0 rounded-full bg-teal-400/15 ring-1 ring-inset ring-teal-300/40" transition={{ type: "spring", stiffness: 380, damping: 32 }} />}
              <span
                className={`relative grid h-5 w-5 place-items-center rounded-full text-[10px] font-bold ${
                  done ? "bg-teal-400 text-ink-950" : on ? "bg-gradient-to-br from-teal-300 to-cyan-400 text-ink-950" : "bg-white/[0.06] text-slate-500"
                }`}
              >
                {done ? <Check size={11} strokeWidth={3} /> : i + 1}
              </span>
              <span className={`relative hidden whitespace-nowrap text-[11px] font-medium ${on ? "text-slate-100 lg:inline" : done ? "text-slate-400 min-[1400px]:inline" : "text-slate-500 min-[1400px]:inline"}`}>{s.label}</span>
            </div>
          </div>
        );
      })}
      {hint === "inline" && (
        <motion.span key={step} initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} className="ml-1 hidden max-w-[220px] truncate border-l border-white/10 pl-3 pr-2 text-[11px] text-slate-400 2xl:inline">
          {STEPS[step].hint}
        </motion.span>
      )}
    </div>
  );
  if (hint === "inline") return pill;
  // On the map pages the hint sits under the pill so it never collides with the side controls.
  return (
    <div className="flex flex-col items-start gap-1.5 sm:items-center">
      {pill}
      <AnimatePresence mode="wait">
        <motion.span
          key={step}
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          className="glass hidden rounded-full px-3 py-1 text-[11px] text-slate-300 sm:inline-block"
        >
          {STEPS[step].hint}
        </motion.span>
      </AnimatePresence>
    </div>
  );
}

export function LayerToggle({
  layer,
  onChange,
  tilt,
  onTilt,
  className = "",
}: {
  layer: "aerial" | "map";
  onChange: (l: "aerial" | "map") => void;
  tilt?: boolean;
  onTilt?: (v: boolean) => void;
  className?: string;
}) {
  const opts = [
    { id: "aerial" as const, label: "Aerial", icon: <Satellite size={13} /> },
    { id: "map" as const, label: "Map", icon: <MapIcon size={13} /> },
  ];
  return (
    <div className={`glass flex items-center gap-0.5 rounded-xl p-1 ${className}`} aria-label="Base map">
      <Layers size={13} className="mx-1.5 hidden text-slate-500 sm:block" />
      {opts.map((o) => (
        <button key={o.id} onClick={() => onChange(o.id)} className={`relative flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[11px] font-medium ${layer === o.id ? "text-ink-950" : "text-slate-300 hover:text-white"}`}>
          {layer === o.id && <motion.span layoutId="layer-toggle" className="absolute inset-0 rounded-lg bg-teal-300" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
          <span className="relative flex items-center gap-1">
            {o.icon}
            <span className="hidden sm:inline">{o.label}</span>
          </span>
        </button>
      ))}
      {onTilt && (
        <>
          <span className="mx-0.5 h-4 w-px bg-white/10" />
          <button
            onClick={() => onTilt(!tilt)}
            aria-pressed={!!tilt}
            title={tilt ? "Switch to a flat, straight-down view (sharpest imagery)" : "Tilt the camera and show buildings in 3D"}
            className={`flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition ${tilt ? "bg-violet-400/20 text-violet-200 ring-1 ring-inset ring-violet-300/40" : "text-slate-300 hover:text-white"}`}
          >
            <Box size={13} />
            <span className="hidden sm:inline">{tilt ? "3D" : "2D"}</span>
          </button>
        </>
      )}
    </div>
  );
}
