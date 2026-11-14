"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Analysis, AnalysisSummary, MetricResult } from "@/lib/api-types";
import { fmtRange, fmtSqft, SEVERITY_STYLE, STATUS_STYLE, titleCase, VERDICT_STYLE } from "@/lib/format";
import { Brand } from "@/components/HealthBadge";
import { Card, Meter, Pill, ScoreRing, Spinner } from "@/components/ui/primitives";

const MAX = 4;

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="grid min-h-dvh place-items-center bg-ink-950"><Spinner /></div>}>
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
    api
      .analyses()
      .then(setSummaries)
      .catch((e: Error) => setError(e.message));
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
  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : s.length >= MAX ? s : [...s, id]));
  const cols = selected.map((id) => details[id]).filter((a): a is Analysis => !!a && !!a.result);

  // Union of metric ids across selected analyses, in first-seen order.
  const metricRows = useMemo(() => {
    const seen = new Map<string, { name: string; group: string }>();
    for (const a of cols) for (const m of a.result!.metrics) if (!seen.has(m.id)) seen.set(m.id, { name: m.name, group: m.group });
    return [...seen];
  }, [cols]);
  const best = cols.length ? Math.max(...cols.map((a) => a.result!.recommendation.score)) : null;

  return (
    <div className="min-h-dvh bg-ink-950">
      <header className="sticky top-0 z-50 border-b border-line bg-ink-950/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-4 py-3">
          <Link href="/">
            <Brand />
          </Link>
          <Link href="/" className="rounded-lg border border-line px-3 py-1.5 text-xs text-slate-300 hover:border-teal-400 hover:text-teal-300">
            ← Back to map
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-7xl space-y-6 px-4 py-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Compare analyzed properties</h1>
          <p className="text-sm text-slate-400">Pick 2–{MAX} completed analyses.</p>
        </div>

        <Card className="p-4">
          {error && <p className="text-sm text-rose-300">{error}</p>}
          {!summaries && !error && <Spinner />}
          {summaries && completed.length === 0 && <p className="text-sm text-slate-500">No completed analyses yet.</p>}
          <div className="flex flex-wrap gap-2">
            {completed.map((s) => {
              const on = selected.includes(s.id);
              return (
                <button
                  key={s.id}
                  onClick={() => toggle(s.id)}
                  className={`max-w-xs rounded-xl border px-3 py-2 text-left text-xs transition ${on ? "border-teal-400 bg-teal-500/10" : "border-line bg-ink-850 hover:border-slate-500"}`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`grid h-4 w-4 place-items-center rounded border ${on ? "border-teal-400 bg-teal-500 text-ink-950" : "border-slate-600"}`}>{on ? "✓" : ""}</span>
                    <span className="truncate font-medium text-slate-100">{s.property.address || `${titleCase(s.property.building_type)} · ${fmtSqft(s.property.area_sqft)}`}</span>
                    {s.score != null && <span className="font-bold text-slate-300">{Math.round(s.score)}</span>}
                  </div>
                  <div className="mt-0.5 truncate pl-6 text-[10px] text-slate-500">
                    {s.business_label} · {new Date(s.created_at).toLocaleDateString()}
                  </div>
                </button>
              );
            })}
          </div>
        </Card>

        {cols.length > 0 && (
          <div className="overflow-x-auto rounded-2xl border border-line">
            <table className="w-full min-w-[640px] border-collapse text-sm">
              <thead>
                <tr className="bg-ink-900">
                  <th className="sticky left-0 z-10 w-48 bg-ink-900 p-3 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500" />
                  {cols.map((a) => {
                    const r = a.result!.recommendation;
                    const v = VERDICT_STYLE[r.verdict];
                    return (
                      <th key={a.id} className="border-l border-line p-4 text-left align-top font-normal">
                        <div className="flex items-start gap-3">
                          <ScoreRing value={r.score} size={72} color={v.color} label="score" />
                          <div className="min-w-0">
                            <Link href={`/analysis/${a.id}`} className="line-clamp-2 text-sm font-semibold text-slate-100 hover:text-teal-300">
                              {a.property.address || `${titleCase(a.property.building_type)} · ${fmtSqft(a.property.area_sqft)}`}
                            </Link>
                            <Pill className={`${v.bg} ${v.text} ${v.ring} mt-1`}>{r.label || v.label}</Pill>
                            {best === r.score && cols.length > 1 && <div className="mt-1 text-[10px] font-semibold text-emerald-300">★ Highest score</div>}
                          </div>
                        </div>
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody className="divide-y divide-line/70">
                <Row label="Business">{cols.map((a) => <td key={a.id} className="border-l border-line p-3 text-slate-300">{a.result!.business_label}</td>)}</Row>
                <Row label="Confidence">
                  {cols.map((a) => (
                    <td key={a.id} className="border-l border-line p-3">
                      <div className="flex items-center gap-2">
                        <Meter value={a.result!.recommendation.confidence} color="#60a5fa" />
                        <span className="w-10 font-mono text-xs text-slate-300">{Math.round(a.result!.recommendation.confidence)}%</span>
                      </div>
                    </td>
                  ))}
                </Row>
                <Row label="Size">{cols.map((a) => <td key={a.id} className="border-l border-line p-3 text-slate-300">{fmtSqft(a.property.area_sqft)}</td>)}</Row>
                <Row label="Upfront cost">{cols.map((a) => <td key={a.id} className="border-l border-line p-3 font-mono text-xs text-slate-200">{a.result!.costs ? fmtRange(a.result!.costs.upfront.low, a.result!.costs.upfront.high) : "—"}</td>)}</Row>
                <Row label="Monthly occupancy">
                  {cols.map((a) => (
                    <td key={a.id} className="border-l border-line p-3 font-mono text-xs text-slate-200">
                      {a.result!.costs?.monthly_occupancy ? fmtRange(a.result!.costs.monthly_occupancy.low, a.result!.costs.monthly_occupancy.high) : "—"}
                    </td>
                  ))}
                </Row>
                <Row label="Dealbreakers">
                  {cols.map((a) => (
                    <td key={a.id} className="border-l border-line p-3 text-xs text-rose-200">
                      {a.result!.recommendation.dealbreakers.length ? a.result!.recommendation.dealbreakers.join("; ") : <span className="text-slate-600">None</span>}
                    </td>
                  ))}
                </Row>
                <tr className="bg-ink-900/60">
                  <td colSpan={cols.length + 1} className="px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-400/80">
                    Metrics
                  </td>
                </tr>
                {metricRows.map(([id, meta]) => (
                  <Row key={id} label={meta.name} sub={meta.group}>
                    {cols.map((a) => {
                      const m: MetricResult | undefined = a.result!.metrics.find((x) => x.id === id);
                      if (!m) return <td key={a.id} className="border-l border-line p-3 text-[11px] text-slate-600">not evaluated</td>;
                      const st = STATUS_STYLE[m.status];
                      return (
                        <td key={a.id} className="border-l border-line p-3" title={m.rationale}>
                          <div className="flex items-center gap-2">
                            <Pill className={st.cls}>{st.label}</Pill>
                            <span className="font-mono text-xs text-slate-400">{m.score == null ? "—" : Math.round(m.score)}</span>
                          </div>
                        </td>
                      );
                    })}
                  </Row>
                ))}
                <tr className="bg-ink-900/60">
                  <td colSpan={cols.length + 1} className="px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-400/80">
                    Top risks
                  </td>
                </tr>
                <Row label="Risks">
                  {cols.map((a) => (
                    <td key={a.id} className="border-l border-line p-3 align-top">
                      <ul className="space-y-1.5">
                        {[...a.result!.risks]
                          .sort((x, y) => ["high", "medium", "low"].indexOf(x.severity) - ["high", "medium", "low"].indexOf(y.severity))
                          .slice(0, 3)
                          .map((r, i) => (
                            <li key={i} className="flex items-start gap-1.5 text-[11px] leading-snug text-slate-300">
                              <Pill className={SEVERITY_STYLE[r.severity]}>{r.severity[0]}</Pill>
                              {r.text}
                            </li>
                          ))}
                      </ul>
                    </td>
                  ))}
                </Row>
              </tbody>
            </table>
          </div>
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

function Row({ label, sub, children }: { label: string; sub?: string; children: React.ReactNode }) {
  return (
    <tr className="hover:bg-ink-900/40">
      <th className="sticky left-0 z-10 bg-ink-950 p-3 text-left align-top text-xs font-medium text-slate-300">
        {label}
        {sub && <div className="text-[10px] font-normal text-slate-600">{sub}</div>}
      </th>
      {children}
    </tr>
  );
}
