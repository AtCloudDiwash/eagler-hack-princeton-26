"use client";

import { AnimatePresence, motion } from "motion/react";
import { Info, MapPin, Ruler, Sparkles, Store, Users, Wallet } from "lucide-react";
import { useState } from "react";
import type { SearchResponse } from "@/lib/api-types";
import { fmtMoney, fmtNum } from "@/lib/format";

const MODE: Record<SearchResponse["data_mode"], { label: string; cls: string }> = {
  vexcel_live: { label: "Vexcel live", cls: "text-teal-300" },
  vexcel_demo: { label: "Vexcel demo", cls: "text-amber-300" },
  osm_only: { label: "OpenStreetMap only", cls: "text-amber-300" },
};

/** What we understood from the query, as compact chips; caveats tucked behind an info toggle. */
export default function IntentChips({ result }: { result: SearchResponse }) {
  const { intent } = result;
  const [showNotes, setShowNotes] = useState(false);
  const chip = "inline-flex items-center gap-1 rounded-full bg-white/[0.05] px-2 py-1 text-[11px] text-slate-200 ring-1 ring-inset ring-white/[0.06]";
  const budget = intent.budget;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={chip}>
          <Store size={11} className="text-teal-300" />
          {intent.business_label}
        </span>
        {intent.seats != null && (
          <span className={chip}>
            <Users size={11} className="text-teal-300" />
            {intent.seats} seats
          </span>
        )}
        {intent.sqft != null && (
          <span className={chip}>
            <Ruler size={11} className="text-teal-300" />
            {fmtNum(intent.sqft)} sq ft
          </span>
        )}
        {(result.location?.name || intent.location_text) && (
          <span className={chip}>
            <MapPin size={11} className="text-teal-300" />
            {result.location?.name ?? intent.location_text}
          </span>
        )}
        {budget ? (
          <span className={chip}>
            <Wallet size={11} className="text-emerald-300" />
            {fmtMoney(budget.amount)}
            {budget.period === "monthly" ? "/mo" : budget.period === "annual" ? "/yr" : " upfront"}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded-full px-2 py-1 text-[11px] text-slate-500 border border-dashed border-white/10" title="Add a budget to your query, e.g. “budget $8k/month”">
            <Wallet size={11} />
            No budget set
          </span>
        )}
        {intent.requirements.slice(0, 3).map((r) => (
          <span key={r} className="rounded-full bg-cyan-400/10 px-2 py-1 text-[11px] text-cyan-200">
            + {r}
          </span>
        ))}
      </div>
      <div className="mt-2 flex items-center gap-3 text-[10px] text-slate-500">
        <span className="flex items-center gap-1">
          <Sparkles size={10} className={intent.parser === "llm" ? "text-teal-300" : "text-slate-500"} />
          {intent.parser === "llm" ? "Understood by AI" : "Rule-based parse"}
        </span>
        <span className={MODE[result.data_mode].cls}>● {MODE[result.data_mode].label}</span>
        {result.notes.length > 0 && (
          <button onClick={() => setShowNotes((v) => !v)} className="flex items-center gap-1 hover:text-slate-300">
            <Info size={10} /> {result.notes.length} note{result.notes.length > 1 ? "s" : ""}
          </button>
        )}
      </div>
      <AnimatePresence>
        {showNotes && (
          <motion.ul initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="mt-2 space-y-1 overflow-hidden">
            {result.notes.map((n, i) => (
              <li key={i} className="rounded-lg bg-amber-400/[0.06] px-2.5 py-1.5 text-[11px] leading-snug text-amber-100/80">
                {n}
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
