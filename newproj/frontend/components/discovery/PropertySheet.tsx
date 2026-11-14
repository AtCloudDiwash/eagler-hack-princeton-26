"use client";

import { motion } from "motion/react";
import { ArrowLeft, Building2, Camera, Car, Database, Fan, Home, Layers3, MapPinned, Microscope, Ruler, Sparkles, Zap } from "lucide-react";
import type { AnalysisMode, Candidate, KeyFact, Neighborhood, PropertyDetail } from "@/lib/api-types";
import { buildingColor, fmtDistance, fmtSqft, titleCase } from "@/lib/format";
import { groupIdForLabel, placeMeta } from "@/lib/places";
import { FieldExplorer } from "@/components/ui/JsonView";
import { Collapsible, ScoreRing, Spinner, StatTile } from "@/components/ui/primitives";
import { candidateTitle } from "./CandidateRail";

type Props = {
  candidate: Candidate;
  detail: PropertyDetail | null;
  detailLoading: boolean;
  detailError: string | null;
  neighborhood: Neighborhood | null;
  neighborhoodLoading: boolean;
  neighborhoodError: string | null;
  radius: number;
  visibleGroups: Set<string> | null;
  setVisibleGroups: (s: Set<string> | null) => void;
  requirements: string;
  setRequirements: (s: string) => void;
  onAnalyze: () => void;
  mode: AnalysisMode;
  setMode: (m: AnalysisMode) => void;
  analyzing: boolean;
  analyzeError: string | null;
  onBack: () => void;
};

const fact = (facts: KeyFact[], label: string) => facts.find((f) => f.label === label)?.value;

function groupFacts(facts: KeyFact[]) {
  const m = new Map<string, KeyFact[]>();
  for (const f of facts) {
    if (!m.has(f.group)) m.set(f.group, []);
    m.get(f.group)!.push(f);
  }
  return [...m];
}

export default function PropertySheet(p: Props) {
  const c = p.detail ?? p.candidate;
  const facts = p.detail?.key_facts ?? [];
  const nb = p.neighborhood;
  const mix = Object.entries(nb?.building_mix ?? {}).sort((a, b) => b[1] - a[1]);
  const mixTotal = mix.reduce((n, [, v]) => n + v, 0);
  const groups = Object.entries(nb?.place_groups ?? {}).sort((a, b) => b[1] - a[1]);

  const toggleGroup = (gid: string) => {
    const all = groups.map(([label]) => groupIdForLabel(label));
    const cur = new Set(p.visibleGroups ?? all);
    if (cur.has(gid)) cur.delete(gid);
    else cur.add(gid);
    p.setVisibleGroups(cur.size === all.length ? null : cur);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <button onClick={p.onBack} className="flex items-center gap-1 text-[11px] text-slate-400 hover:text-teal-300">
          <ArrowLeft size={13} /> All matches
        </button>

        <div className="flex items-start gap-3">
          <ScoreRing value={c.match_score} size={58} color="#f472b6" label="fit" />
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-pink-300/80">Selected building</div>
            <h3 className="mt-0.5 text-[15px] font-semibold leading-snug text-slate-50">{candidateTitle(c)}</h3>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-500">
              <span className="font-mono">
                {c.lat.toFixed(4)}, {c.lon.toFixed(4)}
              </span>
              <span className={c.source === "vexcel" ? "text-teal-300/80" : "text-amber-300/80"}>● {c.source === "vexcel" ? "Vexcel" : c.source}</span>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <StatTile icon={<Ruler size={11} />} label="Footprint" value={fmtSqft(c.area_sqft)} />
          <StatTile icon={<Layers3 size={11} />} label="Stories" value={c.stories_est != null ? `~${c.stories_est}` : "—"} />
          <StatTile icon={<Home size={11} />} label="Roof" value={c.roof_condition != null ? `${c.roof_condition_label ?? ""} ${c.roof_condition.toFixed(1)}` : "—"} accent="#34d399" />
          <StatTile icon={<Fan size={11} />} label="AC units" value={fact(facts, "AC units detected") ?? (p.detailLoading ? "…" : "—")} accent="#e2fb5c" hint="Detected in imagery; units can be hidden" />
          <StatTile icon={<Car size={11} />} label="Paved" value={fact(facts, "Paved (hardscape) area") ?? (p.detailLoading ? "…" : "—")} accent="#94a3b8" />
          <StatTile icon={<Camera size={11} />} label="Imagery" value={p.detail?.imagery?.date?.slice(0, 7) ?? (p.detailLoading ? "…" : "—")} accent="#a78bfa" />
        </div>

        {p.candidate.match_reasons.length > 0 && (
          <ul className="space-y-1">
            {p.candidate.match_reasons.slice(0, 3).map((r) => (
              <li key={r} className="flex items-start gap-2 text-[12px] leading-snug text-slate-300">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-teal-300" />
                {r}
              </li>
            ))}
          </ul>
        )}

        {p.detailError && <p className="rounded-lg bg-rose-500/10 px-3 py-2 text-xs text-rose-200">{p.detailError}</p>}

        <div className="rounded-xl bg-white/[0.025] px-3 ring-1 ring-inset ring-white/[0.05]">
          <Collapsible
            title={
              <span className="flex items-center gap-2">
                <Building2 size={13} className="text-teal-300" /> Building details
              </span>
            }
            count={facts.length || undefined}
          >
            {p.detailLoading && (
              <div className="space-y-1.5">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="skeleton h-3 rounded" />
                ))}
              </div>
            )}
            {groupFacts(facts).map(([g, list]) => (
              <div key={g} className="mb-2.5">
                <div className="mb-1 text-[10px] uppercase tracking-wide text-teal-400/70">{g}</div>
                <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] gap-x-3 gap-y-1 text-[12px]">
                  {list.map((f) => (
                    <div key={f.label} className="contents" title={f.note ?? undefined}>
                      <dt className="text-slate-500">{f.label}</dt>
                      <dd className="text-slate-100">{f.value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
            {p.detail?.raw ? (
              <Collapsible
                title={
                  <span className="flex items-center gap-2">
                    <Database size={12} /> All Vexcel fields & raw JSON
                  </span>
                }
              >
                <FieldExplorer feature={p.detail.raw} />
              </Collapsible>
            ) : (
              p.detail && <p className="pb-2 text-[11px] text-slate-500">No Vexcel record for this building (outside coverage).</p>
            )}
          </Collapsible>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <h4 className="flex items-center gap-2 text-xs font-semibold text-slate-200">
              <MapPinned size={13} className="text-violet-300" /> Surroundings · {fmtDistance(p.radius)}
            </h4>
            {p.neighborhoodLoading && <Spinner className="h-3.5 w-3.5" />}
          </div>
          {p.neighborhoodError && <p className="text-xs text-rose-300">{p.neighborhoodError}</p>}
          {mixTotal > 0 && (
            <div className="mb-3">
              <div className="flex h-2 w-full overflow-hidden rounded-full">
                {mix.map(([t, n]) => (
                  <motion.div key={t} title={`${titleCase(t)}: ${n}`} initial={{ width: 0 }} animate={{ width: `${(n / mixTotal) * 100}%` }} style={{ background: buildingColor(t) }} />
                ))}
              </div>
              <div className="mt-1 text-[10px] text-slate-500">
                {mixTotal} buildings · {mix.slice(0, 3).map(([t, n]) => `${titleCase(t)} ${n}`).join(" · ")}
              </div>
            </div>
          )}
          {groups.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {groups.map(([label, n]) => {
                const gid = groupIdForLabel(label);
                const on = !p.visibleGroups || p.visibleGroups.has(gid);
                return (
                  <button
                    key={label}
                    onClick={() => toggleGroup(gid)}
                    className={`flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] ring-1 ring-inset transition ${on ? "bg-white/[0.05] text-slate-200 ring-white/[0.08]" : "text-slate-600 ring-white/[0.04] line-through"}`}
                  >
                    <i className="h-2 w-2 rounded-full" style={{ background: placeMeta(gid).color, opacity: on ? 1 : 0.3 }} />
                    {label}
                    <span className="font-mono text-slate-500">{n}</span>
                  </button>
                );
              })}
            </div>
          )}
          {!p.neighborhoodLoading && nb && groups.length === 0 && <p className="text-[11px] text-slate-500">No mapped places nearby (or OpenStreetMap is unavailable).</p>}
        </div>
      </div>

      <div className="space-y-2 border-t border-white/[0.06] p-4">
        <input
          value={p.requirements}
          onChange={(e) => p.setRequirements(e.target.value)}
          placeholder="Anything else? e.g. needs a patio, open late"
          className="w-full rounded-xl bg-white/[0.04] px-3 py-2.5 text-[12px] text-slate-100 ring-1 ring-inset ring-white/[0.06] placeholder:text-slate-500 focus:outline-none focus:ring-teal-300/40"
        />
        {p.analyzeError && <p className="text-xs text-rose-300">{p.analyzeError}</p>}
        <ModeToggle mode={p.mode} setMode={p.setMode} />
        <motion.button
          whileHover={{ scale: 1.01 }}
          whileTap={{ scale: 0.98 }}
          onClick={p.onAnalyze}
          disabled={p.analyzing || p.detailLoading}
          className="relative flex w-full items-center justify-center gap-2 overflow-hidden rounded-xl bg-gradient-to-r from-teal-300 via-cyan-300 to-sky-300 px-4 py-3.5 text-sm font-semibold text-ink-950 shadow-lg shadow-cyan-500/25 disabled:opacity-50"
        >
          <motion.span className="absolute inset-y-0 w-1/4 bg-white/40 blur-md" initial={{ x: "-150%" }} animate={{ x: "450%" }} transition={{ duration: 2.6, repeat: Infinity, repeatDelay: 1.2 }} />
          {p.analyzing ? <Spinner className="h-4 w-4 text-ink-950" /> : <Sparkles size={16} />}
          <span className="relative">Analyze this property</span>
        </motion.button>
        <p className="text-center text-[10px] text-slate-500">{MODES[p.mode].caption}</p>
      </div>
    </div>
  );
}

const MODES: Record<AnalysisMode, { label: string; time: string; caption: string; icon: typeof Zap }> = {
  quick: {
    label: "Quick",
    time: "~1 min",
    icon: Zap,
    caption: "Fast answer: agents start from pre-gathered evidence and keep reports brief",
  },
  deep: {
    label: "Deep report",
    time: "~2 min",
    icon: Microscope,
    caption: "Full investigation: each agent decides what to examine, with follow-ups",
  },
};

/** Quick / Deep switch above the Analyze button. */
function ModeToggle({ mode, setMode }: { mode: AnalysisMode; setMode: (m: AnalysisMode) => void }) {
  return (
    <div role="radiogroup" aria-label="Analysis depth" className="grid grid-cols-2 gap-1 rounded-xl bg-white/[0.04] p-1 ring-1 ring-inset ring-white/[0.06]">
      {(Object.keys(MODES) as AnalysisMode[]).map((m) => {
        const { label, time, icon: Icon } = MODES[m];
        const on = mode === m;
        return (
          <button
            key={m}
            role="radio"
            aria-checked={on}
            onClick={() => setMode(m)}
            className={`relative flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-[12px] font-medium transition-colors ${on ? "text-ink-950" : "text-slate-400 hover:text-slate-200"}`}
          >
            {on && <motion.span layoutId="analysis-mode" className="absolute inset-0 rounded-lg bg-teal-300" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
            <Icon size={13} className="relative" />
            <span className="relative">{label}</span>
            <span className={`relative font-mono text-[10px] ${on ? "text-ink-950/70" : "text-slate-500"}`}>{time}</span>
          </button>
        );
      })}
    </div>
  );
}
