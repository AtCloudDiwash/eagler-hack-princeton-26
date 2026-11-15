"use client";

import { AnimatePresence, motion } from "motion/react";
import { History, Scale, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AnalysisSummary } from "@/lib/api-types";
import { fmtFootprint, titleCase, VERDICT_STYLE } from "@/lib/format";
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

  const completed = (items ?? []).filter((i) => i.status === "completed");
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
                {completed.length >= 2 && (
                  <Link href="/compare" className="flex items-center gap-1.5 rounded-lg bg-teal-300 px-3 py-1.5 text-xs font-semibold text-ink-950 hover:bg-teal-200">
                    <Scale size={13} /> Compare
                  </Link>
                )}
                <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-white/[0.06]" aria-label="Close">
                  <X size={16} />
                </button>
              </div>
            </header>
            <motion.div variants={stagger.container} initial="hidden" animate="show" className="flex-1 space-y-2 overflow-y-auto p-4">
              {!items && !error && <Spinner />}
              {error && <p className="text-sm text-rose-300">{error}</p>}
              {items?.length === 0 && <p className="text-sm text-slate-500">No analyses yet. Pick a building and press “Analyze this property”.</p>}
              {items?.map((a) => {
                const v = a.verdict ? VERDICT_STYLE[a.verdict] : null;
                return (
                  <motion.div key={a.id} variants={stagger.item}>
                    <Link href={`/analysis/${a.id}`} className="flex items-center gap-3 rounded-xl bg-white/[0.03] p-3 ring-1 ring-inset ring-white/[0.05] transition hover:bg-white/[0.06] hover:ring-teal-300/30">
                      {a.score != null ? <ScoreRing value={a.score} size={44} color={v?.color} animateIn={false} /> : <span className="grid h-11 w-11 place-items-center rounded-full bg-white/[0.04] text-[10px] text-slate-500">{a.status}</span>}
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-[13px] font-medium text-slate-100">{a.property.address || `${titleCase(a.property.building_type)} · ${fmtFootprint(a.property.area_sqft)}`}</div>
                        <div className="truncate text-[11px] text-slate-500">
                          {a.business_label} · {new Date(a.created_at).toLocaleDateString()}
                        </div>
                        {v && <div className={`mt-0.5 text-[11px] ${v.text}`}>{v.label}</div>}
                      </div>
                    </Link>
                  </motion.div>
                );
              })}
            </motion.div>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
