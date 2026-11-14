"use client";

import { useEffect, useRef } from "react";
import type { Candidate } from "@/lib/api-types";
import { fmtSqft, titleCase } from "@/lib/format";
import { EmptyNote, Meter, Pill } from "@/components/ui/primitives";
import { storiesLabel } from "./PropertyPanel";

type Props = {
  candidates: Candidate[];
  hoveredId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (c: Candidate) => void;
};

const matchColor = (s: number) => (s >= 70 ? "#34d399" : s >= 45 ? "#2dd4bf" : s >= 25 ? "#fbbf24" : "#fb7185");

export default function CandidateList({ candidates, hoveredId, onHover, onSelect }: Props) {
  const refs = useRef(new Map<string, HTMLButtonElement>());
  useEffect(() => {
    if (hoveredId) refs.current.get(hoveredId)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [hoveredId]);

  if (candidates.length === 0) return <EmptyNote>No matching buildings found here. Try a different area or a broader description.</EmptyNote>;

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-slate-200">{candidates.length} candidate buildings</h3>
        <span className="text-[10px] text-slate-500">ranked by pre-screen match · not yet analyzed</span>
      </div>
      <ul className="space-y-1.5">
        {candidates.map((c, i) => (
          <li key={c.id}>
            <button
              ref={(el) => {
                if (el) refs.current.set(c.id, el);
                else refs.current.delete(c.id);
              }}
              onClick={() => onSelect(c)}
              onMouseEnter={() => onHover(c.id)}
              onMouseLeave={() => onHover(null)}
              className={`group w-full rounded-xl border p-3 text-left transition ${
                hoveredId === c.id ? "border-amber-300/60 bg-ink-800" : "border-line bg-ink-850/60 hover:border-teal-500/50 hover:bg-ink-800"
              }`}
            >
              <div className="flex items-start gap-3">
                <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-ink-700 text-[11px] font-bold text-slate-300">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium text-slate-100">{c.address || `${titleCase(c.building_type) || "Building"} · ${fmtSqft(c.area_sqft)}`}</span>
                    <span className="shrink-0 text-xs font-bold" style={{ color: matchColor(c.match_score) }}>
                      {Math.round(c.match_score)}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-400">
                    {c.building_type && <Pill className="bg-ink-700/60 text-slate-300 ring-line">{titleCase(c.building_type)}</Pill>}
                    <span>{fmtSqft(c.area_sqft)}</span>
                    {c.roof_condition != null && <span>· roof {c.roof_condition_label ?? c.roof_condition.toFixed(1)}</span>}
                    {c.stories_est != null && <span>· {storiesLabel(c.stories_est)}</span>}
                    {c.source !== "vexcel" && <Pill className="bg-slate-500/15 text-slate-400 ring-slate-500/30">{c.source}</Pill>}
                  </div>
                  <Meter value={c.match_score} color={matchColor(c.match_score)} className="mt-2 h-1" />
                  {c.match_reasons.length > 0 && <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-slate-500">{c.match_reasons.join(" · ")}</p>}
                </div>
              </div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
