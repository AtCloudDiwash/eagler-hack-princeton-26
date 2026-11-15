"use client";

import { AnimatePresence, motion } from "motion/react";
import { History, Scale, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AnalysisSummary } from "@/lib/api-types";
import { fmtSqft, titleCase, VERDICT_STYLE } from "@/lib/format";
import { ScoreRing, Spinner, stagger } from "@/components/ui/primitives";

/** "Past analyses" slide-over. */
export default function HistoryDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<AnalysisSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setError(null);
    api
      .analyses()
      .then((r) => !cancelled && setItems(r))
      .catch((e: Error) => !cancelled && setError(e.message));
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      cancelled = true;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-[60] flex justify-end bg-black/40 backdrop-blur-sm" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose}>
          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 280, damping: 32 }}
            className="glass-strong flex h-full w-full max-w-md flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="flex items-center justify-between border-b border-white/[0.06] p-4">
              <h2 className="flex items-center gap-2 font-semibold text-slate-100">
                <History size={16} className="text-teal-300" /> Past analyses
              </h2>
              <div className="flex items-center gap-2">
                <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/[0.06]" aria-label="Close">
                  <X size={16} />
                </button>
              </div>
            </header>
            <motion.div variants={stagger.container} initial="hidden" animate="show" className="flex-1 space-y-5 overflow-y-auto p-4">
              {!items && !error && <Spinner />}
              {error && <p className="text-sm text-rose-300">{error}</p>}
              {items?.length === 0 && <p className="text-sm text-slate-500">No analyses yet. Pick a building and press “Analyze this property”.</p>}
              {groupBySearch(items ?? []).map((g) => (
                <motion.section key={g.id} variants={stagger.item} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2 px-1">
                    <div className="min-w-0">
                      <div className="truncate text-[12px] font-semibold text-slate-200">{g.items[0].base_query ?? g.items[0].query}</div>
                      <div className="text-[10px] text-slate-500">
                        {g.items[0].business_label} · {g.items.length} building{g.items.length === 1 ? "" : "s"} analyzed
                      </div>
                    </div>
                    <Link href={`/compare?search=${encodeURIComponent(g.id)}`} className="flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-teal-300 hover:bg-white/[0.06]">
                      <Scale size={12} /> {g.items.filter((i) => i.status === "completed").length >= 2 ? "Compare" : "More buildings"}
                    </Link>
                  </div>
                  {g.items.map((a) => {
                    const v = a.verdict ? VERDICT_STYLE[a.verdict] : null;
                    return (
                      <Link key={a.id} href={`/analysis/${a.id}`} className="flex items-center gap-3 rounded-xl bg-white/[0.03] p-3 ring-1 ring-inset ring-white/[0.05] transition hover:bg-white/[0.06] hover:ring-teal-300/30">
                        {a.score != null ? <ScoreRing value={a.score} size={40} color={v?.color} animateIn={false} label="" /> : <span className="grid h-10 w-10 place-items-center rounded-full bg-white/[0.04] text-[10px] text-slate-500">{a.status}</span>}
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[13px] font-medium text-slate-100">{a.property.address || `${titleCase(a.property.building_type)} · ${fmtSqft(a.property.area_sqft)}`}</div>
                          <div className="truncate text-[11px] text-slate-500">
                            {a.mode === "quick" ? "Quick" : "Deep"} · {new Date(a.created_at).toLocaleDateString()}
                            {v ? <span className={`ml-1 ${v.text}`}>· {v.label}</span> : null}
                          </div>
                        </div>
                      </Link>
                    );
                  })}
                </motion.section>
              ))}
            </motion.div>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Analyses grouped by the search they came from (newest search first). */
function groupBySearch(items: AnalysisSummary[]): { id: string; items: AnalysisSummary[] }[] {
  const map = new Map<string, AnalysisSummary[]>();
  for (const a of items) {
    const key = a.search_id ?? a.id;
    map.set(key, [...(map.get(key) ?? []), a]);
  }
  return [...map.entries()].map(([id, list]) => ({ id, items: list }));
}
