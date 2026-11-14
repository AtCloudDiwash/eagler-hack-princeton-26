"use client";

import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { Evidence } from "@/lib/api-types";
import { AGENT_META } from "@/lib/format";
import { CopyButton, RawJson } from "@/components/ui/JsonView";

type Ctx = { byId: Map<string, Evidence>; open: (id: string) => void };
const EvidenceCtx = createContext<Ctx>({ byId: new Map(), open: () => {} });

/** Provides the evidence index and a slide-over drawer that any EvidenceChip can open. */
export function EvidenceProvider({ evidence, children }: { evidence: Evidence[]; children: ReactNode }) {
  const byId = useMemo(() => new Map(evidence.map((e) => [e.id, e])), [evidence]);
  const [openId, setOpenId] = useState<string | null>(null);
  const open = useCallback((id: string) => setOpenId(id), []);
  const current = openId ? byId.get(openId) : null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpenId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <EvidenceCtx.Provider value={{ byId, open }}>
      {children}
      {openId && (
        <div className="fixed inset-0 z-[3000] flex justify-end bg-black/50 backdrop-blur-sm" onClick={() => setOpenId(null)}>
          <aside
            className="flex h-full w-full max-w-xl flex-col border-l border-line bg-ink-900 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label={`Evidence ${openId}`}
          >
            <header className="flex items-start justify-between gap-3 border-b border-line p-5">
              <div>
                <div className="mb-1 flex items-center gap-2">
                  <span className="rounded-md bg-teal-500/15 px-2 py-0.5 font-mono text-xs font-bold text-teal-300">{openId}</span>
                  {current && (
                    <span className="text-xs" style={{ color: AGENT_META[current.agent]?.color }}>
                      {AGENT_META[current.agent]?.label ?? current.agent}
                    </span>
                  )}
                </div>
                <h3 className="text-base font-semibold text-slate-100">{current?.source ?? "Evidence not found"}</h3>
                {current && <p className="mt-0.5 font-mono text-[11px] text-slate-500">tool: {current.tool}</p>}
              </div>
              <button onClick={() => setOpenId(null)} className="rounded-lg p-1.5 text-slate-400 hover:bg-ink-800 hover:text-slate-100" aria-label="Close">
                ✕
              </button>
            </header>
            <div className="flex-1 space-y-4 overflow-y-auto p-5 text-sm">
              {current ? (
                <>
                  <p className="leading-relaxed text-slate-300">{current.summary}</p>
                  {current.url && (
                    <a href={current.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 break-all text-xs text-teal-300 hover:underline">
                      ↗ {current.url}
                    </a>
                  )}
                  <div>
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Data returned by the tool</span>
                      <CopyButton value={current.data} />
                    </div>
                    <RawJson value={current.data} maxH="max-h-[60vh]" />
                  </div>
                </>
              ) : (
                <p className="text-slate-400">
                  This finding cites <b>{openId}</b>, but no evidence with that id was recorded. The engine marks such findings as unverified.
                </p>
              )}
            </div>
          </aside>
        </div>
      )}
    </EvidenceCtx.Provider>
  );
}

export function EvidenceChips({ ids }: { ids: string[] }) {
  const { byId, open } = useContext(EvidenceCtx);
  if (!ids?.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {ids.map((id) => {
        const ev = byId.get(id);
        return (
          <button
            key={id}
            onClick={(e) => {
              e.stopPropagation();
              open(id);
            }}
            title={ev ? `${ev.source}: ${ev.summary}` : "Missing evidence"}
            className={`rounded px-1.5 py-px font-mono text-[10px] font-semibold ring-1 ring-inset transition ${
              ev ? "bg-teal-500/10 text-teal-300 ring-teal-400/30 hover:bg-teal-500/25" : "bg-rose-500/10 text-rose-300 ring-rose-400/30"
            }`}
          >
            {id}
          </button>
        );
      })}
    </span>
  );
}

export const useEvidence = () => useContext(EvidenceCtx);
