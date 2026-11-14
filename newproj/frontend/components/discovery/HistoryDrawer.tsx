"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AnalysisSummary } from "@/lib/api-types";
import { fmtSqft, titleCase, VERDICT_STYLE } from "@/lib/format";
import { Pill, Spinner } from "@/components/ui/primitives";

/** "Past analyses" slide-over on the discovery page. */
export default function HistoryDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [items, setItems] = useState<AnalysisSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setError(null);
    api
      .analyses()
      .then((r) => {
        if (!cancelled) setItems(r);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  if (!open) return null;
  const completed = (items ?? []).filter((i) => i.status === "completed");
  return (
    <div className="fixed inset-0 z-[3000] flex justify-end bg-black/40 backdrop-blur-sm" onClick={onClose}>
      <aside className="flex h-full w-full max-w-md flex-col border-l border-line bg-ink-900" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-line p-4">
          <h2 className="font-semibold text-slate-100">Past analyses</h2>
          <div className="flex items-center gap-2">
            {completed.length >= 2 && (
              <Link href="/compare" className="rounded-lg bg-teal-500 px-3 py-1.5 text-xs font-semibold text-ink-950 hover:bg-teal-400">
                Compare
              </Link>
            )}
            <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-ink-800" aria-label="Close">
              ✕
            </button>
          </div>
        </header>
        <div className="flex-1 space-y-2 overflow-y-auto p-4">
          {!items && !error && <Spinner />}
          {error && <p className="text-sm text-rose-300">{error}</p>}
          {items?.length === 0 && <p className="text-sm text-slate-500">No analyses yet. Select a building and click “Analyze This Property”.</p>}
          {items?.map((a) => {
            const v = a.verdict ? VERDICT_STYLE[a.verdict] : null;
            return (
              <Link key={a.id} href={`/analysis/${a.id}`} className="block rounded-xl border border-line bg-ink-850/70 p-3 hover:border-teal-500/50">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-slate-100">{a.property.address || `${titleCase(a.property.building_type)} · ${fmtSqft(a.property.area_sqft)}`}</div>
                    <div className="truncate text-[11px] text-slate-500">
                      {a.business_label} · “{a.query}”
                    </div>
                  </div>
                  {a.score != null && <span className="text-lg font-bold text-slate-100">{Math.round(a.score)}</span>}
                </div>
                <div className="mt-1.5 flex items-center gap-2">
                  {v ? <Pill className={`${v.bg} ${v.text} ${v.ring}`}>{v.label}</Pill> : <Pill className="bg-ink-700 text-slate-400 ring-line">{a.status}</Pill>}
                  <span className="text-[10px] text-slate-500">{new Date(a.created_at).toLocaleString()}</span>
                </div>
              </Link>
            );
          })}
        </div>
      </aside>
    </div>
  );
}
