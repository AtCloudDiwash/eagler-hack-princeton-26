"use client";

/**
 * Compare = choosing between buildings for the SAME goal. A comparison is always scoped to one search
 * (e.g. "gym in Houston"): only analyses of buildings from that search's candidate list appear, and the
 * remaining candidates can be analyzed with the same request ("Analyze this one too").
 *   /compare                 -> your searches, grouped
 *   /compare?search=<id>     -> one search: pick analyzed buildings, compare, analyze more
 *   /compare?ids=<id>        -> legacy link: redirects to that analysis's search
 */
import { motion } from "motion/react";
import { ArrowLeft, Check, ChevronRight, Crown, Loader2, Microscope, Plus, Scale, Wallet, Zap } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Analysis, AnalysisSummary, MetricResult, SearchGroup } from "@/lib/api-types";
import { fmtRange, fmtSqft, SEVERITY_STYLE, STATUS_STYLE, titleCase, VERDICT_STYLE } from "@/lib/format";
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
  const searchId = params.get("search");
  const legacyIds = params.get("ids");

  // Old ?ids= links: jump to the search the first analysis belongs to.
  useEffect(() => {
    if (searchId || !legacyIds) return;
    const first = legacyIds.split(",").filter(Boolean)[0];
    if (!first) return;
    api
      .analysis(first)
      .then((a) => a.search_id && router.replace(`/compare?search=${encodeURIComponent(a.search_id)}`))
      .catch(() => router.replace("/compare"));
  }, [searchId, legacyIds, router]);

  return (
    <div className="min-h-dvh bg-ink-950 bg-[radial-gradient(ellipse_80%_50%_at_50%_-10%,rgba(212,245,58,0.10),transparent)]">
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-ink-950/75 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <Brand />
          <div className="flex items-center gap-1">
            {searchId && (
              <Link href="/compare" className="flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[11px] text-slate-300 hover:bg-white/[0.06] hover:text-white">
                <Scale size={14} /> All searches
              </Link>
            )}
            <Link href="/" className="flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[11px] text-slate-300 hover:bg-white/[0.06] hover:text-white">
              <ArrowLeft size={14} /> Back to map
            </Link>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">{searchId ? <SearchCompare id={searchId} /> : <SearchList />}</main>
    </div>
  );
}

// ------------------------------------------------------------------ all searches

function SearchList() {
  const [summaries, setSummaries] = useState<AnalysisSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.analyses().then(setSummaries).catch((e: Error) => setError(e.message));
  }, []);

  const groups = useMemo(() => {
    const map = new Map<string, AnalysisSummary[]>();
    for (const s of summaries ?? []) {
      const key = s.search_id ?? s.id;
      map.set(key, [...(map.get(key) ?? []), s]);
    }
    return [...map.entries()].map(([id, items]) => {
      const done = items.filter((i) => i.status === "completed");
      const scores = done.map((i) => i.score ?? 0);
      return { id, items, done, best: scores.length ? Math.max(...scores) : null, latest: items[0] };
    });
  }, [summaries]);

  return (
    <>
      <div>
        <h1 className="flex items-center gap-2 font-display text-xl font-semibold tracking-tight text-slate-50">
          <Scale size={18} className="text-teal-300" /> Compare buildings
        </h1>
        <p className="text-sm text-slate-400">Comparisons stay within one search, so every building is judged on the same checks for the same goal.</p>
      </div>
      {error && <p className="text-sm text-rose-300">{error}</p>}
      {!summaries && !error && <Spinner />}
      {summaries && groups.length === 0 && <p className="text-sm text-slate-500">No analyses yet. Search, pick a building and analyze it first.</p>}
      <motion.div variants={stagger.container} initial="hidden" animate="show" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {groups.map((g) => (
          <motion.div key={g.id} variants={stagger.item}>
            <Link href={`/compare?search=${encodeURIComponent(g.id)}`} className="glass group flex h-full flex-col rounded-2xl p-4 transition hover:ring-1 hover:ring-teal-300/40">
              <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-300/80">{g.latest.business_label}</div>
              <div className="mt-1 line-clamp-2 text-[14px] font-semibold text-slate-100">{g.latest.base_query ?? g.latest.query}</div>
              <div className="mt-3 flex items-center gap-3 text-[11px] text-slate-400">
                <span>
                  {g.done.length} building{g.done.length === 1 ? "" : "s"} analyzed
                </span>
                {g.best != null && (
                  <span>
                    best <span className="font-mono text-slate-200">{Math.round(g.best)}</span>
                  </span>
                )}
                <span className="ml-auto">{new Date(g.latest.created_at).toLocaleDateString()}</span>
              </div>
              <div className="mt-3 flex items-center gap-1 text-[11px] font-medium text-teal-300 opacity-80 group-hover:opacity-100">
                {g.done.length >= 2 ? "Compare" : "Analyze more buildings"} <ChevronRight size={13} />
              </div>
            </Link>
          </motion.div>
        ))}
      </motion.div>
    </>
  );
}

// ------------------------------------------------------------------ one search

function SearchCompare({ id }: { id: string }) {
  const router = useRouter();
  const [group, setGroup] = useState<SearchGroup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[] | null>(null);
  const [details, setDetails] = useState<Record<string, Analysis>>({});
  const [starting, setStarting] = useState<string | null>(null);
  const [extra, setExtra] = useState<string | null>(null); // extra requirements for new analyses (editable)

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .searchGroup(id)
        .then((g) => {
          if (!alive) return;
          setGroup(g);
          setSelected((s) => s ?? g.analyses.filter((a) => a.status === "completed").slice(0, MAX).map((a) => a.id));
        })
        .catch((e: Error) => alive && setError(e.message));
    load();
    const t = setInterval(load, 8000); // pick up analyses still running
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [id]);

  useEffect(() => {
    const missing = (selected ?? []).filter((x) => !details[x]);
    if (!missing.length) return;
    let cancelled = false;
    Promise.all(missing.map((x) => api.analysis(x).catch(() => null))).then((list) => {
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

  if (error) return <p className="text-sm text-rose-300">{error}</p>;
  if (!group || !selected) return <Spinner />;

  const analyzedProps = new Set(group.analyses.map((a) => a.property.id));
  const remaining = group.candidates.filter((c) => !analyzedProps.has(c.id));
  const completed = group.analyses.filter((a) => a.status === "completed");
  const running = group.analyses.filter((a) => a.status === "queued" || a.status === "running");
  const latest = group.analyses[0];
  const toggle = (x: string) => setSelected((s) => (s!.includes(x) ? s!.filter((y) => y !== x) : s!.length >= MAX ? s : [...s!, x]));
  const cols = selected.map((x) => details[x]).filter((a): a is Analysis => !!a && !!a.result);
  const extraValue = extra ?? latest?.extra_requirements ?? "";
  // Buildings judged against different extra requirements aren't scored on the same terms.
  const extrasUsed = Array.from(new Set(completed.map((a) => (a.extra_requirements ?? "").trim())));

  async function analyzeToo(propertyId: string) {
    if (!group) return;
    setStarting(propertyId);
    try {
      const { id: newId } = await api.startAnalysis({
        query: group.query,
        intent: group.intent,
        property_id: propertyId,
        radius_m: 500,
        requirements: extraValue.trim() || undefined,
        mode: latest?.mode ?? "deep",
        search_id: group.legacy ? undefined : group.id,
      });
      router.push(`/analysis/${newId}`);
    } catch (e) {
      setError((e as Error).message);
      setStarting(null);
    }
  }

  return (
    <>
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-teal-300/80">{group.intent.business_label} · same search</div>
        <h1 className="mt-1 font-display text-xl font-semibold tracking-tight text-slate-50">{group.query}</h1>
        {latest?.extra_requirements && <p className="mt-1 text-sm text-slate-400">Extra requirements: {latest.extra_requirements}</p>}
        {extrasUsed.length > 1 && (
          <p className="mt-1 text-xs text-amber-200/80">
            These analyses used different extra requirements ({extrasUsed.map((e) => (e ? `“${e}”` : "none")).join(" vs ")}), so their scores are not judged on the same terms.
          </p>
        )}
      </div>

      <div className="glass rounded-2xl p-3">
        <div className="mb-2 px-1 text-[11px] font-semibold text-slate-300">
          Analyzed buildings <span className="font-normal text-slate-500">· pick up to {MAX} to compare</span>
        </div>
        {completed.length === 0 && running.length === 0 && <p className="p-1 text-sm text-slate-500">None yet: analyze a building below.</p>}
        <motion.div variants={stagger.container} initial="hidden" animate="show" className="flex flex-wrap gap-2">
          {completed.map((s) => {
            const on = selected.includes(s.id);
            return (
              <motion.button
                key={s.id}
                variants={stagger.item}
                whileTap={{ scale: 0.97 }}
                onClick={() => toggle(s.id)}
                className={`flex max-w-[300px] items-center gap-2.5 rounded-xl px-3 py-2 text-left text-xs ring-1 ring-inset transition ${on ? "bg-teal-400/10 ring-teal-300/40" : "bg-white/[0.03] ring-white/[0.06] hover:ring-white/[0.15]"}`}
              >
                <span className={`grid h-4 w-4 shrink-0 place-items-center rounded ${on ? "bg-teal-300 text-ink-950" : "ring-1 ring-slate-600"}`}>{on && <Check size={11} strokeWidth={3} />}</span>
                <span className="min-w-0">
                  <span className="block truncate font-medium text-slate-100">{s.property.address || `${titleCase(s.property.building_type)} · ${fmtSqft(s.property.area_sqft)}`}</span>
                  <span className="flex items-center gap-1 truncate text-[10px] text-slate-500">
                    {s.mode === "quick" ? <Zap size={9} /> : <Microscope size={9} />} {s.mode === "quick" ? "Quick" : "Deep"} · {new Date(s.created_at).toLocaleDateString()}
                  </span>
                </span>
                {s.score != null && <span className="ml-auto font-semibold text-slate-200">{Math.round(s.score)}</span>}
              </motion.button>
            );
          })}
          {running.map((s) => (
            <Link key={s.id} href={`/analysis/${s.id}`} className="flex items-center gap-2 rounded-xl bg-white/[0.03] px-3 py-2 text-xs text-slate-400 ring-1 ring-inset ring-white/[0.06]">
              <Loader2 size={12} className="animate-spin" /> {s.property.address || titleCase(s.property.building_type)} · analyzing…
            </Link>
          ))}
        </motion.div>
      </div>

      {cols.length > 0 && <Comparison cols={cols} />}
      {selected.length > 0 && cols.length < selected.length && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <Spinner className="h-3 w-3" /> Loading selected analyses…
        </div>
      )}

      {!group.legacy && remaining.length > 0 && (
        <div className="glass rounded-2xl p-3">
          <div className="mb-2 px-1 text-[11px] font-semibold text-slate-300">
            More buildings from this search <span className="font-normal text-slate-500">· analyzed with the same request{latest?.mode === "quick" ? " (Quick)" : ""}</span>
          </div>
          <label className="mb-2 block px-1 text-[11px] text-slate-400">
            Extra requirements for these analyses
            <input
              value={extraValue}
              onChange={(e) => setExtra(e.target.value)}
              placeholder="e.g. budget $6k/month, outdoor patio"
              className="mt-1 w-full rounded-lg bg-white/[0.04] px-2.5 py-1.5 text-xs text-slate-100 ring-1 ring-inset ring-white/[0.08] placeholder:text-slate-600 focus:outline-none focus:ring-teal-300/40"
            />
          </label>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {remaining.slice(0, 12).map((c, i) => (
              <div key={c.id} className="flex items-center gap-3 rounded-xl bg-white/[0.03] p-2.5 ring-1 ring-inset ring-white/[0.06]">
                <ScoreRing value={c.match_score ?? 0} size={36} label="" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12px] font-medium text-slate-100">{c.address || `${titleCase(c.building_type)} · ${fmtSqft(c.area_sqft)}`}</div>
                  <div className="truncate text-[10px] text-slate-500">
                    #{group.candidates.indexOf(c) + 1} match{c.roof_condition_label ? ` · roof ${c.roof_condition_label.toLowerCase()}` : ""}
                    {c.stories_est ? ` · ~${c.stories_est} stories` : ""}
                  </div>
                </div>
                <button
                  onClick={() => analyzeToo(c.id)}
                  disabled={starting !== null}
                  className="flex shrink-0 items-center gap-1 rounded-lg bg-teal-300 px-2.5 py-1.5 text-[11px] font-semibold text-ink-950 hover:bg-teal-200 disabled:opacity-50"
                  aria-label={`Analyze candidate ${i + 1} too`}
                >
                  {starting === c.id ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} Analyze
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
      {group.legacy && (
        <p className="text-[11px] text-slate-500">This search was made before candidate lists were saved, so only its analyzed buildings are shown. Run the search again to analyze more of its buildings.</p>
      )}
    </>
  );
}

// ------------------------------------------------------------------ side by side

function Comparison({ cols }: { cols: Analysis[] }) {
  const metricRows = useMemo(() => {
    const seen = new Map<string, { name: string; group: string }>();
    for (const a of cols) for (const m of a.result!.metrics) if (!seen.has(m.id)) seen.set(m.id, { name: m.name, group: m.group });
    return [...seen];
  }, [cols]);
  const best = cols.length ? Math.max(...cols.map((a) => a.result!.recommendation.score)) : null;
  const title = (a: Analysis) => a.property.address || `${titleCase(a.property.building_type)} · ${fmtSqft(a.property.area_sqft)}`;

  return (
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
            {metricRows.map(([mid, meta]) => (
              <tr key={mid} className="hover:bg-white/[0.02]">
                <th className="sticky left-0 z-10 bg-ink-900/95 p-3 text-left align-top text-xs font-medium text-slate-300">
                  {meta.name}
                  <div className="text-[10px] font-normal text-slate-600">{meta.group}</div>
                </th>
                {cols.map((a) => {
                  const m: MetricResult | undefined = a.result!.metrics.find((x) => x.id === mid);
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
            {cols.some((a) => a.result!.requirement_checks?.length) && (
              <tr>
                <th className="sticky left-0 z-10 bg-ink-900/95 p-3 text-left align-top text-xs font-medium text-slate-300">Your requirements</th>
                {cols.map((a) => (
                  <td key={a.id} className="border-l border-white/[0.05] p-3 align-top">
                    <ul className="space-y-1 text-[11px]">
                      {(a.result!.requirement_checks ?? []).map((c) => (
                        <li key={c.requirement} title={c.rationale} className="flex items-center gap-1.5 text-slate-300">
                          <span className={`h-1.5 w-1.5 rounded-full ${c.status === "met" ? "bg-emerald-400" : c.status === "unmet" ? "bg-rose-400" : "bg-slate-500"}`} />
                          <span className="capitalize">{c.requirement}</span>
                          <span className="text-slate-500">{c.status === "met" ? "met" : c.status === "unmet" ? "not met" : "unverified"}</span>
                        </li>
                      ))}
                    </ul>
                  </td>
                ))}
              </tr>
            )}
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
  );
}
