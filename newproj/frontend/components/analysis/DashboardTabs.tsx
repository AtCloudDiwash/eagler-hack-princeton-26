"use client";

import { AnimatePresence, motion } from "motion/react";
import { AlertTriangle, CheckCircle2, ChevronDown, ExternalLink, HelpCircle, Search, ShieldAlert, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import type { AgentReport, AnalysisResult, ComplianceItem, Costs, MetricResult } from "@/lib/api-types";
import { AGENT_META, COMPLIANCE_STYLE, fmtMoney, fmtRange, SEVERITY_STYLE, STATUS_STYLE } from "@/lib/format";
import { Collapsible, EmptyNote, Pill, RangeBar, stagger, StatTile } from "@/components/ui/primitives";
import { EvidenceChips, useEvidence } from "./EvidenceContext";

// ---------------------------------------------------------------- Overview: metrics

export function MetricsOverview({ metrics, businessLabel }: { metrics: MetricResult[]; businessLabel: string }) {
  const [filter, setFilter] = useState<"all" | "dynamic" | "common">("all");
  const [openId, setOpenId] = useState<string | null>(null);
  const groups = useMemo(() => {
    const m = new Map<string, MetricResult[]>();
    for (const x of [...metrics].sort((a, b) => b.weight - a.weight)) {
      if (filter !== "all" && x.category !== filter) continue;
      if (!m.has(x.group)) m.set(x.group, []);
      m.get(x.group)!.push(x);
    }
    return [...m];
  }, [metrics, filter]);
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-slate-400">
          {metrics.length} checks chosen for a <span className="text-slate-200">{businessLabel.toLowerCase()}</span>. Tap one to see why.
        </p>
        <div className="flex gap-1 text-[11px]">
          {(["all", "dynamic", "common"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)} className={`rounded-lg px-2.5 py-1 ${filter === f ? "bg-white/[0.08] text-slate-100" : "text-slate-500 hover:text-slate-300"}`}>
              {f === "all" ? "All" : f === "dynamic" ? `${businessLabel}-specific` : "Common"}
            </button>
          ))}
        </div>
      </div>
      <div className="space-y-5">
        {groups.map(([g, list]) => (
          <div key={g}>
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">{g}</div>
            <motion.div variants={stagger.container} initial="hidden" animate="show" className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {list.map((m) => (
                <MetricCard key={m.id} m={m} open={openId === m.id} onToggle={() => setOpenId((o) => (o === m.id ? null : m.id))} />
              ))}
            </motion.div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricCard({ m, open, onToggle }: { m: MetricResult; open: boolean; onToggle: () => void }) {
  const st = STATUS_STYLE[m.status];
  return (
    <motion.div variants={stagger.item} layout className={`rounded-xl bg-white/[0.03] ring-1 ring-inset transition-colors ${open ? "ring-teal-300/30" : "ring-white/[0.05] hover:ring-white/[0.12]"} ${open ? "sm:col-span-2 xl:col-span-3" : ""}`}>
      <button onClick={onToggle} className="flex w-full items-center gap-3 p-3 text-left" aria-expanded={open}>
        <span className="relative h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: st.color, boxShadow: `0 0 10px ${st.color}88` }} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-[13px] font-medium text-slate-100">{m.name}</span>
            <span className="shrink-0 font-mono text-[11px] text-slate-400">{m.score == null ? "—" : Math.round(m.score)}</span>
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
              <motion.div className="h-full rounded-full" style={{ background: st.color }} initial={{ width: 0 }} animate={{ width: `${m.score ?? 0}%` }} transition={{ duration: 0.8 }} />
            </div>
            <span className="text-[10px]" style={{ color: st.color }}>
              {st.label}
            </span>
          </div>
        </div>
        <motion.span animate={{ rotate: open ? 180 : 0 }} className="text-slate-500">
          <ChevronDown size={14} />
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="grid gap-3 px-3 pb-3 text-[12px] md:grid-cols-2">
              <div className="space-y-2">
                <p className="leading-relaxed text-slate-200">{m.rationale}</p>
                <p className="text-[11px] leading-snug text-slate-500">
                  <span className="text-slate-400">Why it matters: </span>
                  {m.why_it_matters}
                </p>
              </div>
              <div className="space-y-2">
                {m.facts.length > 0 && (
                  <ul className="space-y-1">
                    {m.facts.map((f, i) => (
                      <li key={i} className="flex gap-1.5 text-[11px] text-slate-300">
                        <CheckCircle2 size={11} className="mt-0.5 shrink-0 text-emerald-400/80" /> {f}
                      </li>
                    ))}
                  </ul>
                )}
                {m.assumptions.length > 0 && (
                  <ul className="space-y-1">
                    {m.assumptions.map((f, i) => (
                      <li key={i} className="flex gap-1.5 text-[11px] text-slate-400">
                        <HelpCircle size={11} className="mt-0.5 shrink-0 text-amber-300/80" /> {f}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="flex items-center gap-2 text-[10px] text-slate-500">
                  <span>{AGENT_META[m.owner_agent]?.short ?? m.owner_agent}</span>·<span>weight {m.weight}</span>
                  {m.evidence_ids.length > 0 && <EvidenceChips ids={m.evidence_ids} />}
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// ---------------------------------------------------------------- Costs

export function CostsTab({ costs }: { costs: Costs | null }) {
  if (!costs) return <EmptyNote>No cost estimate was produced.</EmptyNote>;
  const items = [...costs.fitout.line_items].sort((a, b) => b.high - a.high);
  const max = Math.max(...items.map((i) => i.high), 1);
  return (
    <div className="space-y-5">
      <div className="grid gap-2 sm:grid-cols-3">
        <StatTile label="Upfront to open" value={fmtRange(costs.upfront.low, costs.upfront.high)} accent="#fbbf24" />
        <StatTile label="Monthly occupancy" value={costs.monthly_occupancy ? fmtRange(costs.monthly_occupancy.low, costs.monthly_occupancy.high) : "—"} accent="#d4f53a" />
        <StatTile label="Rent per year" value={costs.rent ? fmtRange(costs.rent.low_annual, costs.rent.high_annual) : "—"} accent="#a78bfa" hint={costs.rent?.source} />
      </div>
      <p className="text-[11px] text-slate-500">{costs.sqft_basis || (costs.sqft_used ? `${costs.sqft_used.toLocaleString()} sq ft` : "")}</p>
      <div className="space-y-3">
        {items.map((l) => (
          <div key={l.id} className="group">
            <div className="mb-1 flex items-baseline justify-between gap-3 text-[12px]">
              <span className="text-slate-200" title={l.reason}>
                {l.label}
              </span>
              <span className="shrink-0 font-mono text-[11px] text-slate-400">{fmtRange(l.low, l.high)}</span>
            </div>
            <RangeBar low={l.low} high={l.high} max={max} color={l.evidence_ids.length ? "#d4f53a" : "#fbbf24"} />
            {(l.reason || l.evidence_ids.length > 0) && (
              <div className="mt-1 flex flex-wrap items-center gap-2 text-[10.5px] text-slate-500">
                {l.reason && <span className="line-clamp-1">{l.reason}</span>}
                <EvidenceChips ids={l.evidence_ids} />
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="flex items-center gap-4 text-[10px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <i className="h-1.5 w-3 rounded-full bg-teal-400" /> backed by evidence
        </span>
        <span className="flex items-center gap-1.5">
          <i className="h-1.5 w-3 rounded-full bg-amber-400" /> planning assumption
        </span>
      </div>
      <Collapsible title="Assumptions behind these numbers" count={costs.assumptions.length}>
        <ul className="space-y-1.5">
          {costs.assumptions.map((a, i) => (
            <li key={i} className="text-[11px] leading-snug text-slate-400">
              • {a}
            </li>
          ))}
        </ul>
      </Collapsible>
    </div>
  );
}

// ---------------------------------------------------------------- Compliance

const COMPLIANCE_ICON = {
  pass: <CheckCircle2 size={16} className="text-emerald-300" />,
  risk: <AlertTriangle size={16} className="text-amber-300" />,
  fail: <XCircle size={16} className="text-rose-300" />,
  unknown: <HelpCircle size={16} className="text-slate-400" />,
} as const;

export function ComplianceTab({ items }: { items: ComplianceItem[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (items.length === 0) return <EmptyNote>No compliance checks recorded.</EmptyNote>;
  return (
    <motion.ul variants={stagger.container} initial="hidden" animate="show" className="space-y-2">
      {items.map((c) => {
        const isOpen = open === c.id;
        return (
          <motion.li key={c.id} variants={stagger.item} className="rounded-xl bg-white/[0.03] ring-1 ring-inset ring-white/[0.05]">
            <button onClick={() => setOpen(isOpen ? null : c.id)} className="flex w-full items-center gap-3 p-3 text-left">
              {COMPLIANCE_ICON[c.status]}
              <span className="min-w-0 flex-1 truncate text-[13px] text-slate-100">{c.rule}</span>
              <Pill className={COMPLIANCE_STYLE[c.status].cls}>{COMPLIANCE_STYLE[c.status].label}</Pill>
              <motion.span animate={{ rotate: isOpen ? 180 : 0 }} className="text-slate-500">
                <ChevronDown size={14} />
              </motion.span>
            </button>
            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                  <div className="space-y-2 px-3 pb-3 pl-10 text-[12px]">
                    <p className="leading-relaxed text-slate-300">{c.detail}</p>
                    {c.citation && (
                      <p className="text-[11px] text-slate-500">
                        {c.url ? (
                          <a href={c.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-teal-300 hover:underline">
                            <ExternalLink size={11} /> {c.citation}
                          </a>
                        ) : (
                          c.citation
                        )}
                      </p>
                    )}
                    <EvidenceChips ids={c.evidence_ids} />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.li>
        );
      })}
    </motion.ul>
  );
}

// ---------------------------------------------------------------- Agents

export function AgentsTab({ agents }: { agents: AgentReport[] }) {
  return (
    <motion.div variants={stagger.container} initial="hidden" animate="show" className="grid gap-3 lg:grid-cols-2">
      {agents.map((a) => {
        const meta = AGENT_META[a.agent];
        return (
          <motion.div key={a.agent} variants={stagger.item} className="rounded-2xl bg-white/[0.03] p-4 ring-1 ring-inset ring-white/[0.05]">
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="flex items-center gap-2.5">
                <span className="grid h-8 w-8 place-items-center rounded-xl text-sm" style={{ background: `${meta.color}1f`, color: meta.color }}>
                  {meta.icon}
                </span>
                <div>
                  <div className="text-[13px] font-semibold text-slate-100">{a.label}</div>
                  <div className="text-[10px] text-slate-500">
                    {a.status} · {a.tool_calls} checks · {a.duration_s.toFixed(0)}s
                  </div>
                </div>
              </div>
            </div>
            <p className="text-[12px] leading-relaxed text-slate-300">{a.summary || a.error || "No summary."}</p>
            {a.findings.length > 0 && (
              <Collapsible title="Findings" count={a.findings.length}>
                <ul className="space-y-2">
                  {a.findings.map((f) => (
                    <li key={f.id} className="rounded-lg bg-black/20 p-2.5">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className={`text-[12px] font-medium ${f.impact === "positive" ? "text-emerald-200" : f.impact === "negative" ? "text-rose-200" : "text-slate-200"}`}>{f.title}</span>
                        <Pill className={SEVERITY_STYLE[f.severity]}>{f.severity}</Pill>
                        <Pill className="bg-white/[0.05] text-slate-400 ring-white/[0.08]">{f.kind}</Pill>
                        {!f.verified && <Pill className="bg-rose-500/15 text-rose-300 ring-rose-400/30">unverified</Pill>}
                      </div>
                      <p className="mt-1 text-[11px] leading-snug text-slate-400">{f.detail}</p>
                      <div className="mt-1">
                        <EvidenceChips ids={f.evidence_ids} />
                      </div>
                    </li>
                  ))}
                </ul>
              </Collapsible>
            )}
            {a.missing_information.length > 0 && (
              <Collapsible title="What the data can't tell" count={a.missing_information.length}>
                <ul className="space-y-1">
                  {a.missing_information.map((m, i) => (
                    <li key={i} className="text-[11px] text-slate-400">
                      • {m}
                    </li>
                  ))}
                </ul>
              </Collapsible>
            )}
            {a.followups.length > 0 && (
              <Collapsible title="Suggested next steps" count={a.followups.length}>
                <ul className="space-y-1">
                  {a.followups.map((m, i) => (
                    <li key={i} className="text-[11px] text-cyan-200/80">
                      → {m}
                    </li>
                  ))}
                </ul>
              </Collapsible>
            )}
          </motion.div>
        );
      })}
    </motion.div>
  );
}

// ---------------------------------------------------------------- Evidence

export function EvidenceTab({ result }: { result: AnalysisResult }) {
  const { open } = useEvidence();
  const [agent, setAgent] = useState<string>("all");
  const [q, setQ] = useState("");
  const agents = useMemo(() => [...new Set(result.evidence.map((e) => e.agent))], [result.evidence]);
  const list = result.evidence.filter((e) => (agent === "all" || e.agent === agent) && (!q || `${e.id} ${e.source} ${e.summary} ${e.tool}`.toLowerCase().includes(q.toLowerCase())));
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="flex min-w-[180px] flex-1 items-center gap-2 rounded-xl bg-white/[0.04] px-3 py-2 ring-1 ring-inset ring-white/[0.06]">
          <Search size={13} className="text-slate-500" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search evidence…" className="w-full bg-transparent text-xs text-slate-100 placeholder:text-slate-500 focus:outline-none" />
        </label>
        {["all", ...agents].map((a) => (
          <button key={a} onClick={() => setAgent(a)} className={`rounded-lg px-2.5 py-1.5 text-[11px] ${agent === a ? "bg-white/[0.08] text-slate-100" : "text-slate-500 hover:text-slate-300"}`}>
            {a === "all" ? `All ${result.evidence.length}` : AGENT_META[a as keyof typeof AGENT_META]?.short ?? a}
          </button>
        ))}
      </div>
      <div className="divide-y divide-white/[0.05] overflow-hidden rounded-xl bg-white/[0.02] ring-1 ring-inset ring-white/[0.05]">
        {list.map((e) => (
          <button key={e.id} onClick={() => open(e.id)} className="flex w-full items-start gap-3 p-3 text-left transition hover:bg-white/[0.04]">
            <span className="w-9 shrink-0 font-mono text-xs font-bold text-teal-300">{e.id}</span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-[12px]">
                <span className="font-medium text-slate-200">{e.source}</span>
                <span className="text-[10px]" style={{ color: AGENT_META[e.agent]?.color }}>
                  {AGENT_META[e.agent]?.short ?? e.agent}
                </span>
              </div>
              <p className="mt-0.5 line-clamp-1 text-[11px] text-slate-400">{e.summary}</p>
            </div>
          </button>
        ))}
        {list.length === 0 && <p className="p-4 text-xs text-slate-500">No evidence matches.</p>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- More details

const SRC_CLS = { used: "text-emerald-300", unavailable: "text-slate-500", demo: "text-amber-300" } as const;

export function MoreDetails({ result }: { result: AnalysisResult }) {
  const order = { high: 0, medium: 1, low: 2 } as const;
  const risks = [...result.risks].sort((a, b) => order[a.severity] - order[b.severity]);
  return (
    <div className="divide-y divide-white/[0.05]">
      <Collapsible title={<span className="flex items-center gap-2"><ShieldAlert size={13} className="text-rose-300" /> Risks</span>} count={risks.length}>
        <ul className="space-y-2">
          {risks.map((r, i) => (
            <li key={i} className="flex items-start gap-2 text-[12px] text-slate-300">
              <Pill className={`${SEVERITY_STYLE[r.severity]} mt-0.5`}>{r.severity}</Pill>
              <span>
                {r.text} <span className="text-[10px]" style={{ color: AGENT_META[r.agent]?.color }}>· {AGENT_META[r.agent]?.short}</span>
              </span>
            </li>
          ))}
          {risks.length === 0 && <li className="text-xs text-slate-500">No risks flagged.</li>}
        </ul>
      </Collapsible>
      <Collapsible title={<span className="flex items-center gap-2"><HelpCircle size={13} className="text-amber-300" /> Open questions</span>} count={result.open_questions.length}>
        <ul className="space-y-2">
          {result.open_questions.map((q, i) => (
            <li key={i} className="rounded-lg bg-black/20 p-2.5">
              <div className="text-[12px] text-slate-100">{q.question}</div>
              <div className="mt-0.5 text-[11px] text-cyan-200/80">→ {q.suggested_source}</div>
            </li>
          ))}
        </ul>
      </Collapsible>
      {(result.conflicts.length > 0 || result.followups_run.length > 0) && (
        <Collapsible title="How the agents were reconciled" count={result.conflicts.length + result.followups_run.length}>
          <ul className="space-y-2 text-[12px]">
            {result.conflicts.map((c, i) => (
              <li key={`c${i}`} className="rounded-lg bg-amber-400/[0.05] p-2.5">
                <div className="text-slate-200">{c.description}</div>
                <div className="mt-1 text-[11px] text-emerald-300/90">Resolution: {c.resolution}</div>
              </li>
            ))}
            {result.followups_run.map((f, i) => (
              <li key={`f${i}`} className="rounded-lg bg-black/20 p-2.5">
                <div className="text-[11px]" style={{ color: AGENT_META[f.agent]?.color }}>
                  ↻ Follow-up · {AGENT_META[f.agent]?.short}
                </div>
                <div className="mt-0.5 text-slate-300">{f.outcome}</div>
              </li>
            ))}
          </ul>
        </Collapsible>
      )}
      <Collapsible title="Data sources" count={result.data_sources.length}>
        <ul className="grid gap-1.5 sm:grid-cols-2">
          {result.data_sources.map((s) => (
            <li key={s.name} className="rounded-lg bg-black/20 p-2.5 text-[11px]">
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-200">{s.name}</span>
                <span className={SRC_CLS[s.status]}>● {s.status}</span>
              </div>
              <div className="mt-0.5 text-slate-500">{s.note}</div>
            </li>
          ))}
        </ul>
      </Collapsible>
    </div>
  );
}

export const moneyOrDash = (n: number | null | undefined) => (n == null ? "—" : fmtMoney(n));
