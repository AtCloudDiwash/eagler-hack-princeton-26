"use client";

import type { SearchResponse } from "@/lib/api-types";
import { Pill } from "@/components/ui/primitives";

const MODE: Record<SearchResponse["data_mode"], { label: string; cls: string; title: string }> = {
  vexcel_live: { label: "Vexcel live", cls: "bg-teal-500/15 text-teal-300 ring-teal-400/30", title: "Live Vexcel property data" },
  vexcel_demo: { label: "Demo data", cls: "bg-amber-500/15 text-amber-300 ring-amber-400/30", title: "Recorded Vexcel sample data (no API key)" },
  osm_only: { label: "OSM only", cls: "bg-slate-500/20 text-slate-300 ring-slate-400/30", title: "Outside Vexcel coverage — OpenStreetMap footprints only" },
};

export default function IntentBar({ result }: { result: SearchResponse }) {
  const { intent, location, data_mode, notes } = result;
  const chips: [string, string | null][] = [
    ["Business", intent.business_label],
    ["Location", location?.name ?? intent.location_text],
    ["Seats", intent.seats != null ? String(intent.seats) : null],
    ["Size", intent.sqft != null ? `${intent.sqft.toLocaleString()} sq ft` : null],
  ];
  const mode = MODE[data_mode];
  return (
    <div className="rounded-xl border border-line bg-ink-850/70 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Understood as</span>
        <div className="flex gap-1">
          <Pill className={mode.cls} title={mode.title}>
            {mode.label}
          </Pill>
          <Pill className="bg-ink-700/60 text-slate-400 ring-line" title="How the query was parsed">
            {intent.parser === "llm" ? "LLM parsed" : "Rule parsed"}
          </Pill>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {chips
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <span key={k} className="rounded-lg bg-ink-700/50 px-2 py-1 text-xs">
              <span className="text-slate-500">{k} </span>
              <span className="font-medium text-slate-100">{v}</span>
            </span>
          ))}
        {intent.requirements.map((r) => (
          <span key={r} className="rounded-lg bg-teal-500/10 px-2 py-1 text-xs text-teal-200">
            + {r}
          </span>
        ))}
      </div>
      {notes.length > 0 && (
        <ul className="mt-2 space-y-1">
          {notes.map((n, i) => (
            <li key={i} className="flex gap-1.5 text-[11px] leading-snug text-amber-200/90">
              <span>ⓘ</span>
              <span>{n}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
