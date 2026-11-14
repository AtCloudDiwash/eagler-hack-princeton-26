"use client";

import { useState } from "react";
import type { AgentReport, Finding } from "@/lib/api-types";
import { AGENT_META, SEVERITY_STYLE } from "@/lib/format";
import { Card, Pill, SectionTitle } from "@/components/ui/primitives";
import { EvidenceChips } from "./EvidenceContext";

const STATUS_CLS: Record<AgentReport["status"], string> = {
  completed: "bg-emerald-500/15 text-emerald-300 ring-emerald-400/30",
  partial: "bg-amber-500/15 text-amber-300 ring-amber-400/30",
  failed: "bg-rose-500/15 text-rose-300 ring-rose-400/30",
  skipped: "bg-slate-500/15 text-slate-400 ring-slate-400/30",
};

export default function AgentReports({ agents }: { agents: AgentReport[] }) {
  const [active, setActive] = useState(agents[0]?.agent ?? "vexcel");
  const current = agents.find((a) => a.agent === active) ?? agents[0];
  return (
    <section>
      <SectionTitle id="agents" eyebrow="Multi-agent investigation" title="Individual agent conclusions" />
      <div className="mb-3 flex gap-1.5 overflow-x-auto pb-1">
        {agents.map((a) => {
          const meta = AGENT_META[a.agent];
          return (
            <button
              key={a.agent}
              onClick={() => setActive(a.agent)}
              className={`flex shrink-0 items-center gap-2 rounded-xl border px-3 py-2 text-left text-xs transition ${
                active === a.agent ? "border-teal-400/60 bg-ink-800" : "border-line bg-ink-900/70 hover:bg-ink-850"
              }`}
            >
              <span style={{ color: meta?.color }}>{meta?.icon}</span>
              <span className="font-medium text-slate-200">{meta?.short ?? a.label}</span>
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  a.status === "completed" ? "bg-emerald-400" : a.status === "partial" ? "bg-amber-400" : a.status === "failed" ? "bg-rose-400" : "bg-slate-500"
                }`}
              />
              <span className="text-[10px] text-slate-500">{a.findings.length}</span>
            </button>
          );
        })}
      </div>
      {current && <AgentDetail a={current} />}
    </section>
  );
}

function AgentDetail({ a }: { a: AgentReport }) {
  const meta = AGENT_META[a.agent];
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl text-lg" style={{ background: `${meta?.color}22`, color: meta?.color }}>
            {meta?.icon}
          </span>
          <div>
            <h3 className="font-semibold text-slate-100">{a.label}</h3>
            <div className="text-[11px] text-slate-500">
              {a.tool_calls} tool calls · {a.duration_s.toFixed(1)}s
            </div>
          </div>
        </div>
        <Pill className={STATUS_CLS[a.status]}>{a.status}</Pill>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-slate-300">{a.summary}</p>
      {a.error && <p className="mt-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-2 text-xs text-rose-200">{a.error}</p>}

      {a.findings.length > 0 && (
        <div className="mt-4 space-y-2">
          {a.findings.map((f) => (
            <FindingRow key={f.id} f={f} />
          ))}
        </div>
      )}

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <ListBox title="Missing information" items={a.missing_information} tone="text-slate-300" icon="?" />
        <ListBox title="Contradictions" items={a.contradictions} tone="text-amber-200" icon="≠" />
        <ListBox title="Suggested follow-up" items={a.followups} tone="text-cyan-200" icon="→" />
      </div>
    </Card>
  );
}

const IMPACT: Record<Finding["impact"], { icon: string; cls: string }> = {
  positive: { icon: "▲", cls: "text-emerald-400" },
  negative: { icon: "▼", cls: "text-rose-400" },
  neutral: { icon: "●", cls: "text-slate-500" },
};
const KIND_CLS: Record<Finding["kind"], string> = {
  fact: "bg-sky-500/15 text-sky-300 ring-sky-400/30",
  inference: "bg-violet-500/15 text-violet-300 ring-violet-400/30",
  assumption: "bg-amber-500/15 text-amber-300 ring-amber-400/30",
};

function FindingRow({ f }: { f: Finding }) {
  const [open, setOpen] = useState(false);
  const imp = IMPACT[f.impact];
  return (
    <div className={`rounded-xl border bg-ink-950/40 p-3 ${f.verified ? "border-line" : "border-rose-500/40"}`}>
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-start gap-2.5 text-left">
        <span className={`mt-0.5 text-[10px] ${imp.cls}`}>{imp.icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[13px] font-medium text-slate-100">{f.title}</span>
            <Pill className={SEVERITY_STYLE[f.severity]}>{f.severity}</Pill>
            <Pill className={KIND_CLS[f.kind]}>{f.kind}</Pill>
            {!f.verified && (
              <Pill className="bg-rose-500/15 text-rose-300 ring-rose-400/30" title="Cited evidence that the engine could not find">
                unverified
              </Pill>
            )}
          </div>
          <p className={`mt-1 text-[12px] leading-snug text-slate-400 ${open ? "" : "line-clamp-2"}`}>{f.detail}</p>
        </div>
      </button>
      {open && (
        <div className="ml-5 mt-2 space-y-1.5 text-[12px]">
          <p className="text-slate-300">
            <span className="text-slate-500">Why it matters: </span>
            {f.why_it_matters}
          </p>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-slate-500">Evidence</span>
            {f.evidence_ids.length ? <EvidenceChips ids={f.evidence_ids} /> : <span className="text-[11px] text-slate-600">none cited</span>}
            {f.metric_ids.length > 0 && <span className="text-[11px] text-slate-600">· metrics: {f.metric_ids.join(", ")}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

function ListBox({ title, items, tone, icon }: { title: string; items: string[]; tone: string; icon: string }) {
  return (
    <div className="rounded-xl border border-line bg-ink-950/30 p-3">
      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">{title}</div>
      {items.length === 0 ? (
        <p className="text-[11px] text-slate-600">None</p>
      ) : (
        <ul className="space-y-1">
          {items.map((t, i) => (
            <li key={i} className={`flex gap-1.5 text-[12px] leading-snug ${tone}`}>
              <span className="text-slate-500">{icon}</span>
              {t}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
