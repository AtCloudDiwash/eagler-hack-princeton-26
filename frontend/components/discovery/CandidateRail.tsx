"use client";

import { AnimatePresence, motion } from "motion/react";
import { Building2, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { Candidate, SearchResponse } from "@/lib/api-types";
import { fmtDistance, fmtFootprint, fmtNum, titleCase } from "@/lib/format";
import { ScoreRing, stagger } from "@/components/ui/primitives";
import IntentChips from "./IntentChips";
import { ProgramPanel } from "@/components/program/SpaceProgram";

type Props = {
  result: SearchResponse;
  hoveredId: string | null;
  onHover: (id: string | null) => void;
  onSelect: (c: Candidate) => void;
};

export const candidateTitle = (c: Candidate) => c.building_name || c.address || `${titleCase(c.building_type) || "Building"} · ${fmtFootprint(c.area_sqft)}`;
/** The size line: listed space beats rentable area beats the aerial footprint. */
export const candidateSize = (c: Candidate) =>
  c.best_space?.sqft
    ? `${c.best_space.sqft_min ? `${fmtNum(c.best_space.sqft_min)}–` : ""}${fmtNum(c.best_space.sqft)} sq ft available`
    : c.rentable_sqft
      ? `${fmtNum(c.rentable_sqft)} sq ft rentable`
      : fmtFootprint(c.area_sqft);
export const candidateMeta = (c: Candidate) =>
  [
    c.distance_m != null && `${fmtDistance(c.distance_m)} away`,
    c.roof_condition_label && `Roof ${c.roof_condition_label.toLowerCase()}`,
    c.stories_est != null && `~${c.stories_est} ${c.stories_est === 1 ? "story" : "stories"}`,
    c.source !== "vexcel" && c.source,
  ]
    .filter(Boolean)
    .join(" · ");

const scoreColor = (s: number) => (s >= 85 ? "#34d399" : s >= 65 ? "#d4f53a" : s >= 45 ? "#fbbf24" : "#fb7185");

function Card({ c, i, hovered, onHover, onSelect, compact = false }: { c: Candidate; i: number; hovered: boolean; onHover: (id: string | null) => void; onSelect: (c: Candidate) => void; compact?: boolean }) {
  return (
    <motion.button
      variants={stagger.item}
      layout
      onMouseEnter={() => onHover(c.id)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(c.id)}
      onClick={() => onSelect(c)}
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.98 }}
      className={`group flex w-full items-center gap-3 rounded-xl p-2.5 text-left transition-colors ${hovered ? "bg-teal-400/10 ring-1 ring-inset ring-teal-300/30" : "bg-white/[0.025] ring-1 ring-inset ring-white/[0.05] hover:bg-white/[0.05]"} ${compact ? "w-[250px] shrink-0 snap-start" : ""}`}
    >
      <ScoreRing value={c.match_score} size={40} color={scoreColor(c.match_score)} animateIn={false} label="fit" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-[10px] text-slate-500">{String(i + 1).padStart(2, "0")}</span>
          <span className="truncate text-[13px] font-medium text-slate-100">{candidateTitle(c)}</span>
        </div>
        <div className="truncate text-[11px] text-slate-400">
          {c.space_count ? <span className="mr-1 rounded bg-emerald-400/15 px-1 text-[10px] font-semibold text-emerald-200">For lease</span> : null}
          {[candidateSize(c), candidateMeta(c)].filter(Boolean).join(" · ")}
        </div>
      </div>
      <ChevronRight size={15} className="shrink-0 text-slate-600 transition-transform group-hover:translate-x-0.5 group-hover:text-teal-300" />
    </motion.button>
  );
}

/** Ranked candidates: floating side panel on desktop, swipeable strip on mobile. */
export default function CandidateRail({ result, hoveredId, onHover, onSelect }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const cands = result.candidates;

  return (
    <>
      {/* Desktop */}
      <motion.aside
        initial={{ opacity: 0, x: -24 }}
        animate={{ opacity: 1, x: collapsed ? -300 : 0 }}
        exit={{ opacity: 0, x: -24 }}
        transition={{ type: "spring", stiffness: 260, damping: 30 }}
        className="glass pointer-events-auto absolute bottom-28 left-4 top-20 z-20 hidden w-[340px] flex-col rounded-2xl sm:flex"
      >
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="glass absolute -right-9 top-4 grid h-8 w-8 place-items-center rounded-xl text-slate-300 hover:text-teal-200"
          aria-label={collapsed ? "Show candidates" : "Hide candidates"}
        >
          {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
        <div className="border-b border-white/[0.06] p-4 pb-3">
          <div className="mb-2.5 flex items-baseline justify-between">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100">
              <Building2 size={15} className="text-teal-300" />
              {cands.length} matching buildings
            </h2>
            <span className="text-[10px] text-slate-500">ranked by fit</span>
          </div>
          <IntentChips result={result} />
        </div>
        <motion.div variants={stagger.container} initial="hidden" animate="show" className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-3">
          {result.program && (
            <div className="-mt-3 mb-2">
              <ProgramPanel program={result.program} />
            </div>
          )}
          {cands.map((c, i) => (
            <Card key={c.id} c={c} i={i} hovered={hoveredId === c.id} onHover={onHover} onSelect={onSelect} />
          ))}
          {cands.length === 0 && <p className="p-4 text-center text-xs text-slate-500">No suitable buildings found here. Try a nearby area or a different business.</p>}
        </motion.div>
      </motion.aside>

      {/* Mobile */}
      <AnimatePresence>
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="pointer-events-auto absolute inset-x-0 bottom-[92px] z-20 sm:hidden">
          <div className="mx-4 mb-2 glass rounded-xl px-3 py-2">
            <IntentChips result={result} />
          </div>
          <motion.div variants={stagger.container} initial="hidden" animate="show" className="flex snap-x gap-2 overflow-x-auto px-4 pb-1">
            {cands.map((c, i) => (
              <div key={c.id} className="glass shrink-0 rounded-xl">
                <Card c={c} i={i} hovered={hoveredId === c.id} onHover={onHover} onSelect={onSelect} compact />
              </div>
            ))}
          </motion.div>
        </motion.div>
      </AnimatePresence>
    </>
  );
}
