"use client";

import type { Candidate, KeyFact, Neighborhood, PropertyDetail } from "@/lib/api-types";
import { fmtSqft, titleCase } from "@/lib/format";
import { Collapsible, Pill, Spinner } from "@/components/ui/primitives";

export const storiesLabel = (n: number) => `~${n} ${n === 1 ? "story" : "stories"}`;
import { FieldExplorer } from "@/components/ui/JsonView";
import NeighborhoodControls from "./NeighborhoodControls";

type Props = {
  candidate: Candidate;
  detail: PropertyDetail | null;
  detailLoading: boolean;
  detailError: string | null;
  radius: number;
  setRadius: (r: number) => void;
  neighborhood: Neighborhood | null;
  neighborhoodLoading: boolean;
  neighborhoodError: string | null;
  onBack: () => void;
  resultCount: number;
};

function groupFacts(facts: KeyFact[]) {
  const m = new Map<string, KeyFact[]>();
  for (const f of facts) {
    if (!m.has(f.group)) m.set(f.group, []);
    m.get(f.group)!.push(f);
  }
  return [...m];
}

export default function PropertyPanel(p: Props) {
  const c = p.detail ?? p.candidate;
  const groups = groupFacts(p.detail?.key_facts ?? []);

  return (
    <div className="space-y-3">
      <button onClick={p.onBack} className="text-xs text-slate-400 hover:text-teal-300">
        ← Back to {p.resultCount} {p.resultCount === 1 ? "candidate" : "candidates"}
      </button>

      <div className="rounded-xl border border-rose-400/30 bg-gradient-to-br from-rose-500/10 to-transparent p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-rose-300/80">Selected building</div>
            <h3 className="mt-0.5 text-base font-semibold leading-snug text-slate-50">
              {c.address || `${titleCase(c.building_type) || "Building"} · ${fmtSqft(c.area_sqft)}`}
            </h3>
            <p className="font-mono text-[11px] text-slate-500">
              {c.lat.toFixed(5)}, {c.lon.toFixed(5)}
            </p>
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold text-slate-100">{Math.round(c.match_score)}</div>
            <div className="text-[9px] uppercase tracking-wide text-slate-500">pre-screen</div>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {c.building_type && <Pill className="bg-ink-700/60 text-slate-200 ring-line">{titleCase(c.building_type)}</Pill>}
          <Pill className="bg-ink-700/60 text-slate-200 ring-line">{fmtSqft(c.area_sqft)}</Pill>
          {c.roof_condition != null && (
            <Pill className="bg-ink-700/60 text-slate-200 ring-line">
              Roof {c.roof_condition_label ?? ""} {c.roof_condition.toFixed(1)}/5
            </Pill>
          )}
          {c.stories_est != null && <Pill className="bg-ink-700/60 text-slate-200 ring-line">{storiesLabel(c.stories_est)}</Pill>}
          <Pill className={c.source === "vexcel" ? "bg-teal-500/15 text-teal-300 ring-teal-400/30" : "bg-amber-500/15 text-amber-300 ring-amber-400/30"}>
            {c.source}
          </Pill>
        </div>
        {p.candidate.match_reasons.length > 0 && <p className="mt-2 text-[11px] leading-snug text-slate-400">{p.candidate.match_reasons.join(" · ")}</p>}
      </div>

      {/* Key facts */}
      <div className="rounded-xl border border-line bg-ink-850/60 p-3">
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Building data</h4>
          {p.detail?.imagery && (
            <span className="text-[10px] text-slate-500">
              {p.detail.imagery.collection ?? "Vexcel"}
              {p.detail.imagery.date ? ` · ${p.detail.imagery.date.slice(0, 10)}` : ""}
              {p.detail.imagery.gsd_m ? ` · ${(p.detail.imagery.gsd_m * 100).toFixed(0)} cm GSD` : ""}
            </span>
          )}
        </div>
        {p.detailLoading && (
          <div className="space-y-1.5">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-3.5 rounded" />
            ))}
          </div>
        )}
        {p.detailError && <p className="text-xs text-rose-300">{p.detailError}</p>}
        {groups.map(([g, facts]) => (
          <div key={g} className="mb-2 last:mb-0">
            <div className="mb-0.5 text-[10px] uppercase tracking-wide text-teal-400/70">{g}</div>
            <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] gap-x-3 gap-y-1 text-xs">
              {facts.map((f) => (
                <div key={f.label} className="contents">
                  <dt className="text-slate-500">{f.label}</dt>
                  <dd className="text-slate-100">
                    {f.value}
                    {f.note && <div className="text-[10px] leading-snug text-slate-500">{f.note}</div>}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        ))}
        {p.detail?.raw && (
          <Collapsible title="All Vexcel fields & raw JSON">
            <FieldExplorer feature={p.detail.raw} />
          </Collapsible>
        )}
        {p.detail && !p.detail.raw && <p className="mt-2 text-[11px] text-slate-500">No Vexcel record for this building (outside coverage).</p>}
      </div>

      {/* Neighborhood */}
      <div className="rounded-xl border border-line bg-ink-850/60 p-3">
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-300">Surroundings</h4>
        <NeighborhoodControls
          radius={p.radius}
          setRadius={p.setRadius}
          neighborhood={p.neighborhood}
          loading={p.neighborhoodLoading}
          error={p.neighborhoodError}
        />
      </div>

    </div>
  );
}

/** Pinned panel footer: optional extra requirements + the button that starts the agents. */
export function AnalyzeBar(p: {
  requirements: string;
  setRequirements: (s: string) => void;
  onAnalyze: () => void;
  analyzing: boolean;
  disabled: boolean;
  error: string | null;
}) {
  return (
    <div className="space-y-2 border-t border-line bg-ink-900/95 p-4">
      <textarea
        value={p.requirements}
        onChange={(e) => p.setRequirements(e.target.value)}
        rows={2}
        placeholder="Extra requirements (optional) — e.g. needs a patio, budget under $8k/month, open late"
        className="w-full resize-none rounded-lg border border-line bg-ink-950/70 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-500 focus:border-teal-500/60 focus:outline-none"
      />
      {p.error && <p className="text-xs text-rose-300">{p.error}</p>}
      <button
        onClick={p.onAnalyze}
        disabled={p.analyzing || p.disabled}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-teal-400 to-cyan-400 px-4 py-3 text-sm font-bold text-ink-950 shadow-lg shadow-teal-500/20 hover:from-teal-300 hover:to-cyan-300 disabled:opacity-50"
      >
        {p.analyzing ? <Spinner className="h-4 w-4 text-ink-950" /> : "◎"} Analyze This Property
      </button>
      <p className="text-center text-[10px] text-slate-500">Starts the Vexcel, Neighborhood, Compliance and Cost agents</p>
    </div>
  );
}
