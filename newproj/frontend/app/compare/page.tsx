"use client";

import { motion } from "motion/react";
import { ArrowLeft, Check, Crown, Scale, Wallet } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Analysis, AnalysisSummary, MetricResult } from "@/lib/api-types";
import { fmtRange, fmtFootprint, SEVERITY_STYLE, STATUS_STYLE, titleCase, VERDICT_STYLE } from "@/lib/format";
import { Brand } from "@/components/shell/Shell";
import { Meter, Pill, ScoreRing, Spinner, stagger } from "@/components/ui/primitives";

const MAX = 4;
const BUDGET_CLS = { within: "text-emerald-300", partly: "text-amber-300", over: "text-rose-300" } as const;

export default function ComparePage() {
  return (
    <Suspense
      fallback={
        <div className="grid min-h-dvh place-items-center bg-ink-950">
          <Spinner />
        </div>
      }
    >
      <Compare />
    </Suspense>
  );
}

function Compare() {
  const router = useRouter();
  const params = useSearchParams();
  const [summaries, setSummaries] = useState<AnalysisSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>(() => (params.get("ids") ?? "").split(",").filter(Boolean).slice(0, MAX));
  const [details, setDetails] = useState<Record<string, Analysis>>({});

  useEffect(() => {
    api.analyses().then(setSummaries).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    const missing = selected.filter((id) => !details[id]);
    if (missing.length === 0) return;
    let cancelled = false;
    Promise.all(missing.map((id) => api.analysis(id).catch(() => null))).then((list) => {
      if (cancelled) return;
      setDetails((d) => {
        const n = { ...d };
        for (const a of list) if (a) n[a.id] = a;
        return n;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [selected, details]);

  useEffect(() => {
    router.replace(selected.length ? `/compare?ids=${selected.join(",")}` : "/compare", { scroll: false });
  }, [selected, router]);

  const completed = (summaries ?? []).filter((s) => s.status === "completed");
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= MAX ? s : [...s, id]));
  const cols = selected.map((id) => details[id]).filter((a): a is Analysis => !!a && !!a.result);
  const metricRows = useMemo(() => {
    const seen = new Map<string, { name: string; group: string }>();
    for (const a of cols) for (const m of a.result!.metrics) if (!seen.has(m.id)) seen.set(m.id, { name: m.name, group: m.group });
    return [...seen];
  }, [cols]);
  const best = cols.length ? Math.max(...cols.map((a) => a.result!.recommendation.score)) : null;
  const title = (a: Analysis) => a.property.address || `${titleCase(a.property.building_type)} · ${fmtFootprint(a.property.area_sqft)}`;

  return (
    <div className="min-h-dvh bg-ink-950 bg-[radial-gradient(ellipse_80%_50%_at_50%_-10%,rgba(212, 245, 58,0.10),transparent)]">
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-ink-950/75 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <Brand />
          <Link href="/" className="flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[11px] text-slate-300 hover:bg-white/[0.06] hover:text-white">
            <ArrowLeft size={14} /> Back to map
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight text-slate-50">
            <Scale size={18} className="text-teal-300" /> Compare buildings
          </h1>
          <p className="text-sm text-slate-400">Pick 2–{MAX} analyzed buildings to see them side by side.</p>
        </div>

        <div className="glass rounded-2xl p-3">
          {error && <p className="p-2 text-sm text-rose-300">{error}</p>}
          {!summaries && !error && <Spinner />}
          {summaries && completed.length === 0 && <p className="p-2 text-sm text-slate-500">No completed analyses yet.</p>}
          <motion.div variants={stagger.container} initial="hidden" animate="show" className="flex flex-wrap gap-2">
            {completed.map((s) => {
              const on = selected.includes(s.id);
              return (
                <motion.button
                  key={s.id}
                  variants={stagger.item}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => toggle(s.id)}
                  className={`flex max-w-[280px] items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs ring-1 ring-inset transition ${on ? "bg-teal-400/10 ring-teal-300/40" : "bg-white/[0.03] ring-white/[0.06] hover:ring-white/[0.15]"}`}
                >
                  <span className={`grid h-4 w-4 shrink-0 place-items-center rounded ${on ? "bg-teal-300 text-ink-950" : "ring-1 ring-slate-600"}`}>{on && <Check size={11} strokeWidth={3} />}</span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-slate-100">{s.property.address || `${titleCase(s.property.building_type)} · ${fmtFootprint(s.property.area_sqft)}`}</span>
                    <span className="block truncate text-[10px] text-slate-500">
                      {s.business_label} · {new Date(s.created_at).toLocaleDateString()}
                    </span>
                  </span>
                  {s.score != null && <span className="ml-auto font-semibold text-slate-200">{Math.round(s.score)}</span>}
                </motion.button>
              );
            })}
          </motion.div>
        </div>

        {cols.length > 0 && (
          <>
            <motion.div variants={stagger.container} initial="hidden" animate="show" className={`grid gap-3 sm:grid-cols-2 ${cols.length > 2 ? "lg:grid-cols-4" : ""}`}>
              {cols.map((a) => {
                const r = a.result!.recommendation;
                const v = VERDICT_STYLE[r.verdict];
                const b = a.result!.costs?.budget;
                const winner = best === r.score && cols.length > 1;
                return (
                  <motion.div key={a.id} variants={stagger.item} className={`glass relative rounded-2xl p-4 ${winner ? "ring-1 ring-emerald-300/40" : ""}`}>
                    {winner && (
                      <span className="absolute right-3 top-3 flex items-center gap-1 rounded-full bg-emerald-400/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-200">
                        <Crown size={11} /> Best fit
                      </span>
                    )}
                    <ScoreRing value={r.score} size={84} color={v.color} label="score" />
                    <Link href={`/analysis/${a.id}`} className="mt-3 line-clamp-2 block text-[13px] font-semibold text-slate-100 hover:text-teal-200">
                      {title(a)}
                    </Link>
                    <div className={`mt-1 text-[11px] ${v.text}`}>{r.label || v.label}</div>
                    <div className="mt-3 space-y-1.5 text-[11px]">
                      <div className="flex items-center justify-between text-slate-400">
                        <span>Confidence</span>
                        <span className="font-mono text-slate-200">{Math.round(r.confidence)}%</span>
                      </div>
                      <Meter value={r.confidence} color="#60a5fa" />
                      <div className="flex justify-between pt-1 text-slate-400">
                        <span>Upfront</span>
                        <span className="font-mono text-slate-200">{a.result!.costs ? fmtRange(a.result!.costs.upfront.low, a.result!.costs.upfront.high) : "—"}</span>
                      </div>
                      <div className="flex justify-between text-slate-400">
                        <span>Monthly</span>
                        <span className="font-mono text-slate-200">{a.result!.costs?.monthly_occupancy ? fmtRange(a.result!.costs.monthly_occupancy.low, a.result!.costs.monthly_occupancy.high) : "—"}</span>
                      </div>
                      {b && (
                        <div className={`flex items-center gap-1 pt-1 ${BUDGET_CLS[b.status]}`}>
                          <Wallet size={11} /> {b.status === "within" ? "Within" : b.status === "partly" ? "Partly within" : "Over"} {b.source === "user" ? "your budget" : "typical budget"}
                        </div>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </motion.div>

            <div className="glass overflow-x-auto rounded-2xl">
              <table className="w-full min-w-[620px] border-collapse text-sm">
                <thead>
                  <tr>
                    <th className="sticky left-0 z-10 w-48 bg-ink-900/95 p-3 text-left text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">Check</th>
                    {cols.map((a) => (
                      <th key={a.id} className="border-l border-white/[0.05] p-3 text-left text-[11px] font-medium text-slate-300">
                        <span className="line-clamp-1">{title(a)}</span>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {metricRows.map(([id, meta]) => (
                    <tr key={id} className="hover:bg-white/[0.02]">
                      <th className="sticky left-0 z-10 bg-ink-900/95 p-3 text-left align-top text-xs font-medium text-slate-300">
                        {meta.name}
                        <div className="text-[10px] font-normal text-slate-600">{meta.group}</div>
                      </th>
                      {cols.map((a) => {
                        const m: MetricResult | undefined = a.result!.metrics.find((x) => x.id === id);
                        if (!m) return <td key={a.id} className="border-l border-white/[0.05] p-3 text-[11px] text-slate-600">not evaluated</td>;
                        const st = STATUS_STYLE[m.status];
                        return (
                          <td key={a.id} className="border-l border-white/[0.05] p-3" title={m.rationale}>
                            <div className="flex items-center gap-2">
                              <span className="h-2 w-2 rounded-full" style={{ background: st.color }} />
                              <span className="text-[12px] text-slate-200">{st.label}</span>
                              <span className="font-mono text-[11px] text-slate-500">{m.score == null ? "" : Math.round(m.score)}</span>
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                  <tr>
                    <th className="sticky left-0 z-10 bg-ink-900/95 p-3 text-left align-top text-xs font-medium text-slate-300">Top risks</th>
                    {cols.map((a) => (
                      <td key={a.id} className="border-l border-white/[0.05] p-3 align-top">
                        <ul className="space-y-1.5">
                          {[...a.result!.risks]
                            .sort((x, y) => ["high", "medium", "low"].indexOf(x.severity) - ["high", "medium", "low"].indexOf(y.severity))
                            .slice(0, 3)
                            .map((r, i) => (
                              <li key={i} className="flex items-start gap-1.5 text-[11px] leading-snug text-slate-300">
                                <Pill className={SEVERITY_STYLE[r.severity]}>{r.severity[0]}</Pill>
                                <span className="line-clamp-2">{r.text}</span>
                              </li>
                            ))}
                        </ul>
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </>
        )}
        {selected.length > 0 && cols.length < selected.length && (
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Spinner className="h-3 w-3" /> Loading selected analyses…
          </div>
        )}
      </main>
    </div>
  );
}
