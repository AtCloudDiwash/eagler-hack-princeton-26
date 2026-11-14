"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentName, Analysis, AnalysisEvent } from "@/lib/api-types";
import { AGENT_META } from "@/lib/format";
import { Card, Spinner } from "@/components/ui/primitives";

const ORDER: AgentName[] = ["engine", "vexcel", "neighborhood", "compliance", "cost", "matterport"];

const EVENT_ICON: Record<AnalysisEvent["type"], string> = {
  start: "▶",
  plan: "◇",
  tool_call: "→",
  tool_result: "←",
  thinking: "…",
  done: "✓",
  error: "✕",
  skipped: "⤼",
  followup: "↻",
  validation: "✔",
};

type AgentState = "waiting" | "running" | "done" | "error" | "skipped";

function stateOf(events: AnalysisEvent[], analysisDone: boolean): AgentState {
  if (events.length === 0) return analysisDone ? "skipped" : "waiting";
  const last = [...events].reverse().find((e) => ["done", "error", "skipped"].includes(e.type));
  const lastIdx = last ? events.lastIndexOf(last) : -1;
  const reopened = events.slice(lastIdx + 1).some((e) => e.type === "followup" || e.type === "start" || e.type === "tool_call");
  if (last && !reopened) return last.type === "done" ? "done" : last.type === "error" ? "error" : "skipped";
  return analysisDone ? "done" : "running";
}

const STATE_STYLE: Record<AgentState, { label: string; cls: string }> = {
  waiting: { label: "Waiting", cls: "text-slate-500" },
  running: { label: "Investigating", cls: "text-teal-300" },
  done: { label: "Done", cls: "text-emerald-300" },
  error: { label: "Failed", cls: "text-rose-300" },
  skipped: { label: "Skipped", cls: "text-slate-400" },
};

/** Live, per-agent stream of what the multi-agent engine is doing. */
export default function AgentTimeline({ analysis }: { analysis: Analysis }) {
  const finished = analysis.status === "completed" || analysis.status === "failed";
  const byAgent = useMemo(() => {
    const m = new Map<AgentName, AnalysisEvent[]>();
    for (const a of ORDER) m.set(a, []);
    for (const e of analysis.events) {
      if (!m.has(e.agent)) m.set(e.agent, []);
      m.get(e.agent)!.push(e);
    }
    return m;
  }, [analysis.events]);

  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (finished) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [finished]);
  const started = new Date(analysis.created_at).getTime();
  const elapsed = Number.isFinite(started) ? Math.max(0, Math.round((now - started) / 1000)) : null;
  const toolCalls = analysis.events.filter((e) => e.type === "tool_call").length;
  const latest = analysis.events[analysis.events.length - 1];

  return (
    <div className="space-y-4">
      <Card className="relative overflow-hidden p-5">
        <div className="pointer-events-none absolute -right-20 -top-20 h-64 w-64 rounded-full bg-teal-500/10 blur-3xl" />
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            {!finished ? <Spinner className="h-8 w-8" /> : <span className="text-3xl">{analysis.status === "failed" ? "✕" : "✓"}</span>}
            <div>
              <h2 className="text-lg font-semibold text-slate-100">
                {analysis.status === "queued" ? "Queued — starting agents…" : finished ? "Investigation finished" : "Agents are investigating this property"}
              </h2>
              <p className="text-xs text-slate-400">
                Local LLM (Ollama) runs usually take 1–4 minutes. Each agent decides which evidence to examine for “{analysis.intent.business_label}”.
              </p>
            </div>
          </div>
          <div className="flex gap-5 text-center">
            <Stat label="Elapsed" value={elapsed != null && !finished ? `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}` : "—"} />
            <Stat label="Tool calls" value={String(toolCalls)} />
            <Stat label="Events" value={String(analysis.events.length)} />
          </div>
        </div>
        {latest && !finished && (
          <p className="mt-3 truncate rounded-lg bg-ink-950/60 px-3 py-2 font-mono text-[11px] text-slate-400">
            <span style={{ color: AGENT_META[latest.agent]?.color }}>{AGENT_META[latest.agent]?.short ?? latest.agent}</span> · {latest.message}
          </p>
        )}
        {analysis.error && <p className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-200">{analysis.error}</p>}
      </Card>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {[...byAgent].map(([agent, events]) => (
          <AgentCard key={agent} agent={agent} events={events} state={stateOf(events, finished)} />
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="font-mono text-xl font-semibold text-slate-100">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}

function AgentCard({ agent, events, state }: { agent: AgentName; events: AnalysisEvent[]; state: AgentState }) {
  const meta = AGENT_META[agent] ?? { label: agent, color: "#94a3b8", icon: "•", role: "", short: agent };
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);
  const st = STATE_STYLE[state];
  return (
    <Card className={`flex h-72 flex-col p-4 ${state === "running" ? "ring-1 ring-teal-400/30" : ""}`}>
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg text-sm" style={{ background: `${meta.color}22`, color: meta.color }}>
            {meta.icon}
          </span>
          <div>
            <div className="text-sm font-semibold text-slate-100">{meta.label}</div>
            <div className="text-[10px] text-slate-500">{meta.role}</div>
          </div>
        </div>
        <span className={`flex items-center gap-1 text-[11px] font-medium ${st.cls}`}>
          {state === "running" && <Spinner className="h-3 w-3" />}
          {st.label}
        </span>
      </div>
      <div ref={scroller} className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
        {events.length === 0 && <p className="pt-6 text-center text-[11px] text-slate-600">{state === "skipped" ? "Not needed for this analysis" : "Waiting for the orchestrator…"}</p>}
        {events.map((e, i) => (
          <div key={i} className="flex gap-2 text-[11px] leading-snug">
            <span className="w-9 shrink-0 text-right font-mono text-slate-600">{e.t.toFixed(0)}s</span>
            <span
              className={`w-3 shrink-0 text-center ${
                e.type === "error" ? "text-rose-400" : e.type === "done" ? "text-emerald-400" : e.type === "followup" ? "text-amber-300" : "text-slate-500"
              }`}
            >
              {EVENT_ICON[e.type] ?? "•"}
            </span>
            <span className={`min-w-0 break-words ${e.type === "tool_call" ? "font-mono text-cyan-200/90" : e.type === "error" ? "text-rose-300" : "text-slate-300"}`}>
              {e.message}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}
