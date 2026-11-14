"use client";

import { useMemo, useState } from "react";
import type { MetricResult } from "@/lib/api-types";
import { AGENT_META, STATUS_STYLE } from "@/lib/format";
import { Card, Meter, Pill, SectionTitle } from "@/components/ui/primitives";
import { EvidenceChips } from "./EvidenceContext";

/** Renders any number of metrics from config, grouped by `group` — no per-metric components. */
export default function MetricsGrid({ metrics, businessLabel }: { metrics: MetricResult[]; businessLabel: string }) {
  const [filter, setFilter] = useState<"all" | "dynamic" | "common">("all");
  const groups = useMemo(() => {
    const m = new Map<string, MetricResult[]>();
    for (const x of metrics) {
      if (filter !== "all" && x.category !== filter) continue;
      if (!m.has(x.group)) m.set(x.group, []);
      m.get(x.group)!.push(x);
    }
    for (const list of m.values()) list.sort((a, b) => b.weight - a.weight);
    return [...m];
  }, [metrics, filter]);
  const dynamicCount = metrics.filter((m) => m.category === "dynamic").length;

  return (
    <section>
      <SectionTitle
        id="metrics"
        eyebrow="Evaluation"
        title={`${businessLabel}-specific metrics`}
        right={
          <div className="flex overflow-hidden rounded-lg border border-line text-[11px]">
            {(
              [
                ["all", `All ${metrics.length}`],
                ["dynamic", `${businessLabel} ${dynamicCount}`],
                ["common", `Common ${metrics.length - dynamicCount}`],
              ] as const
            ).map(([k, label]) => (
              <button key={k} onClick={() => setFilter(k)} className={`px-2.5 py-1 ${filter === k ? "bg-teal-500 text-ink-950" : "text-slate-400 hover:bg-ink-800"}`}>
                {label}
              </button>
            ))}
          </div>
        }
      />
      <div className="space-y-5">
        {groups.map(([group, list]) => (
          <div key={group}>
            <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              {group}
              <span className="h-px flex-1 bg-line" />
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {list.map((m) => (
                <MetricCard key={m.id} m={m} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function MetricCard({ m }: { m: MetricResult }) {
  const [open, setOpen] = useState(false);
  const st = STATUS_STYLE[m.status];
  const agent = AGENT_META[m.owner_agent];
  return (
    <Card className={`flex flex-col p-4 ${m.status === "blocker" ? "border-rose-500/40" : ""}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold leading-snug text-slate-100">{m.name}</h3>
          <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-500">
            <span style={{ color: agent?.color }}>{agent?.short ?? m.owner_agent}</span>
            <span>· weight {m.weight}</span>
            {m.category === "dynamic" && <span className="text-teal-400/80">· business-specific</span>}
          </div>
        </div>
        <Pill className={st.cls}>{st.label}</Pill>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Meter value={m.score} color={st.color} className="h-1.5" />
        <span className="w-8 text-right font-mono text-xs text-slate-300">{m.score == null ? "—" : Math.round(m.score)}</span>
      </div>
      <p className="mt-2 text-[12px] leading-snug text-slate-300">{m.rationale || "No assessment recorded."}</p>
      <p className="mt-1.5 text-[11px] leading-snug text-slate-500">
        <span className="text-slate-400">Why it matters: </span>
        {m.why_it_matters}
      </p>
      <div className="mt-auto pt-2">
        {(m.facts.length > 0 || m.assumptions.length > 0 || m.evidence_ids.length > 0) && (
          <button onClick={() => setOpen((o) => !o)} className="text-[11px] text-teal-300 hover:text-teal-200">
            {open ? "Hide evidence" : `Evidence (${m.facts.length} facts · ${m.assumptions.length} assumptions)`}
          </button>
        )}
        {open && (
          <div className="mt-2 space-y-2 rounded-lg bg-ink-950/50 p-2.5 text-[11px]">
            {m.facts.length > 0 && (
              <div>
                <div className="mb-0.5 font-semibold text-slate-300">Facts</div>
                <ul className="list-disc space-y-0.5 pl-4 text-slate-300">
                  {m.facts.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              </div>
            )}
            {m.assumptions.length > 0 && (
              <div>
                <div className="mb-0.5 font-semibold text-amber-300/90">Assumptions</div>
                <ul className="list-disc space-y-0.5 pl-4 text-slate-400">
                  {m.assumptions.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
              </div>
            )}
            {m.evidence_ids.length > 0 && (
              <div className="flex items-center gap-1.5">
                <span className="text-slate-500">Sources</span>
                <EvidenceChips ids={m.evidence_ids} />
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
