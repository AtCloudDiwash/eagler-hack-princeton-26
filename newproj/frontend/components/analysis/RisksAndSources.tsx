"use client";

import { useMemo, useState } from "react";
import type { AnalysisResult } from "@/lib/api-types";
import { AGENT_META, SEVERITY_STYLE } from "@/lib/format";
import { Card, EmptyNote, Pill, SectionTitle } from "@/components/ui/primitives";
import { useEvidence } from "./EvidenceContext";

export function RisksAndQuestions({ result }: { result: AnalysisResult }) {
  const order = { high: 0, medium: 1, low: 2 } as const;
  const risks = [...result.risks].sort((a, b) => order[a.severity] - order[b.severity]);
  return (
    <section>
      <SectionTitle id="risks" eyebrow="Due diligence" title="Risks & unresolved questions" />
      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Risks ({risks.length})</h3>
          {risks.length === 0 ? (
            <p className="text-xs text-slate-500">No risks flagged.</p>
          ) : (
            <ul className="space-y-2">
              {risks.map((r, i) => (
                <li key={i} className="flex items-start gap-2.5 text-[13px] leading-snug text-slate-200">
                  <Pill className={`${SEVERITY_STYLE[r.severity]} mt-0.5 w-16 justify-center`}>{r.severity}</Pill>
                  <span className="min-w-0 flex-1">
                    {r.text} <span className="text-[10px]" style={{ color: AGENT_META[r.agent]?.color }}>· {AGENT_META[r.agent]?.short ?? r.agent}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Open questions ({result.open_questions.length})</h3>
          {result.open_questions.length === 0 ? (
            <p className="text-xs text-slate-500">Nothing unresolved.</p>
          ) : (
            <ul className="space-y-2.5">
              {result.open_questions.map((q, i) => (
                <li key={i} className="rounded-lg bg-ink-950/40 p-2.5">
                  <div className="text-[13px] font-medium text-slate-100">{q.question}</div>
                  <div className="mt-0.5 text-[11px] leading-snug text-slate-400">{q.why}</div>
                  <div className="mt-1 text-[11px] text-cyan-300/90">
                    → {q.suggested_source} <span className="text-slate-600">· {AGENT_META[q.agent]?.short ?? q.agent}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </section>
  );
}

export function ConflictsAndFollowups({ result }: { result: AnalysisResult }) {
  if (result.conflicts.length === 0 && result.followups_run.length === 0) return null;
  return (
    <section>
      <SectionTitle id="reconciliation" eyebrow="Orchestrator" title="How the agents were reconciled" />
      <div className="grid gap-3 lg:grid-cols-2">
        <Card className="p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Conflicting findings ({result.conflicts.length})</h3>
          {result.conflicts.length === 0 ? (
            <p className="text-xs text-slate-500">No contradictions between agents.</p>
          ) : (
            <ul className="space-y-2.5">
              {result.conflicts.map((c, i) => (
                <li key={i} className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-2.5 text-[12px]">
                  <div className="text-slate-200">{c.description}</div>
                  <div className="mt-1 text-[11px] text-slate-500">
                    Agents: {c.agents.map((a) => AGENT_META[a]?.short ?? a).join(", ")}
                  </div>
                  <div className="mt-1 text-[11px] text-emerald-300/90">Resolution: {c.resolution}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card className="p-4">
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Targeted follow-ups ({result.followups_run.length})</h3>
          {result.followups_run.length === 0 ? (
            <p className="text-xs text-slate-500">No follow-up investigations were needed.</p>
          ) : (
            <ul className="space-y-2.5">
              {result.followups_run.map((f, i) => (
                <li key={i} className="rounded-lg bg-ink-950/40 p-2.5 text-[12px]">
                  <div className="text-[11px]" style={{ color: AGENT_META[f.agent]?.color }}>
                    ↻ {AGENT_META[f.agent]?.label ?? f.agent}
                  </div>
                  <div className="mt-0.5 text-slate-200">{f.question}</div>
                  <div className="mt-1 text-[11px] text-slate-400">{f.outcome}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </section>
  );
}

const SRC_CLS = {
  used: "bg-emerald-500/15 text-emerald-300 ring-emerald-400/30",
  unavailable: "bg-slate-500/15 text-slate-400 ring-slate-400/30",
  demo: "bg-amber-500/15 text-amber-300 ring-amber-400/30",
} as const;

export function DataSources({ result }: { result: AnalysisResult }) {
  return (
    <section>
      <SectionTitle id="sources" eyebrow="Evidence availability" title="Data sources" />
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {result.data_sources.map((s) => (
          <Card key={s.name} className="p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-slate-100">{s.name}</span>
              <Pill className={SRC_CLS[s.status]}>{s.status}</Pill>
            </div>
            <p className="mt-1 text-[11px] leading-snug text-slate-500">{s.note}</p>
          </Card>
        ))}
        {result.data_sources.length === 0 && <EmptyNote>No data source information.</EmptyNote>}
      </div>
    </section>
  );
}

export function EvidenceExplorer({ result }: { result: AnalysisResult }) {
  const { open } = useEvidence();
  const [agent, setAgent] = useState<string>("all");
  const [q, setQ] = useState("");
  const agents = useMemo(() => [...new Set(result.evidence.map((e) => e.agent))], [result.evidence]);
  const list = result.evidence.filter(
    (e) => (agent === "all" || e.agent === agent) && (!q || `${e.id} ${e.source} ${e.summary} ${e.tool}`.toLowerCase().includes(q.toLowerCase())),
  );
  return (
    <section>
      <SectionTitle
        id="evidence"
        eyebrow="Traceability"
        title={`Evidence explorer (${result.evidence.length})`}
        right={
          <div className="flex gap-2">
            <select value={agent} onChange={(e) => setAgent(e.target.value)} className="rounded-lg border border-line bg-ink-900 px-2 py-1 text-xs text-slate-300">
              <option value="all">All agents</option>
              {agents.map((a) => (
                <option key={a} value={a}>
                  {AGENT_META[a]?.short ?? a}
                </option>
              ))}
            </select>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter…"
              className="w-32 rounded-lg border border-line bg-ink-900 px-2 py-1 text-xs text-slate-200 placeholder:text-slate-600 focus:outline-none"
            />
          </div>
        }
      />
      <Card className="divide-y divide-line/60">
        {list.map((e) => (
          <button key={e.id} onClick={() => open(e.id)} className="flex w-full items-start gap-3 p-3 text-left hover:bg-ink-850">
            <span className="w-9 shrink-0 font-mono text-xs font-bold text-teal-300">{e.id}</span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-[12px]">
                <span className="font-medium text-slate-200">{e.source}</span>
                <span className="font-mono text-[10px] text-slate-500">{e.tool}</span>
                <span className="text-[10px]" style={{ color: AGENT_META[e.agent]?.color }}>
                  {AGENT_META[e.agent]?.short ?? e.agent}
                </span>
              </div>
              <p className="mt-0.5 line-clamp-2 text-[11px] leading-snug text-slate-400">{e.summary}</p>
            </div>
            <span className="text-slate-600">›</span>
          </button>
        ))}
        {list.length === 0 && <p className="p-4 text-xs text-slate-500">No evidence matches.</p>}
      </Card>
    </section>
  );
}
