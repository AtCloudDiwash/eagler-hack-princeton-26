"use client";

import { AnimatePresence, motion, useScroll, useMotionValueEvent } from "motion/react";
import { ArrowLeft, BadgeCheck, Box, ClipboardList, Building2, ChevronDown, CircleDollarSign, FileSearch, Gauge, Landmark, MapPinned, PlayCircle, Scale, ThumbsDown, ThumbsUp, Users, Wallet } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import type { Analysis, AnalysisResult, Costs } from "@/lib/api-types";
import { fmtMoney, fmtRange, fmtFootprint, titleCase, VERDICT_STYLE } from "@/lib/format";
import { fmtClock } from "@/lib/humanize";
import { Brand, Stepper } from "@/components/shell/Shell";
import { Meter, ScoreRing, stagger, Tabs } from "@/components/ui/primitives";
import { AgentsTab, ComplianceTab, CostsTab, EvidenceTab, MetricsOverview, MoreDetails } from "./DashboardTabs";
import { EvidenceChips } from "./EvidenceContext";
import LocationTab from "./LocationTab";
import { InteriorTab } from "@/components/matterport/Matterport";
import { NeedsTab } from "@/components/program/SpaceProgram";

type Tab = "overview" | "needs" | "location" | "interior" | "costs" | "compliance" | "agents" | "evidence";

const BUDGET_UI = {
  within: { label: "Within budget", color: "#34d399", cls: "bg-emerald-400/15 text-emerald-200" },
  partly: { label: "Partly within budget", color: "#fbbf24", cls: "bg-amber-400/15 text-amber-200" },
  over: { label: "Over budget", color: "#fb7185", cls: "bg-rose-400/15 text-rose-200" },
} as const;

export default function Dashboard({ analysis, onReplay, demo = false }: { analysis: Analysis; onReplay?: () => void; demo?: boolean }) {
  const result = analysis.result as AnalysisResult;
  const rec = result.recommendation;
  const v = VERDICT_STYLE[rec.verdict];
  const p = analysis.property;
  const { scrollY } = useScroll();
  const [compact, setCompact] = useState(false);
  useMotionValueEvent(scrollY, "change", (y) => setCompact(y > 360));
  const [tab, setTab] = useState<Tab>("overview");
  const [expanded, setExpanded] = useState(false);
  const duration = analysis.events.length ? analysis.events[analysis.events.length - 1].t : null;
  const budget = result.costs?.budget;
  const title = p.address || `${titleCase(p.building_type) || "Building"} · ${fmtFootprint(p.area_sqft)}`;

  const pros = rec.key_reasons.filter((r) => r.impact === "positive").slice(0, 3);
  const cons = rec.key_reasons.filter((r) => r.impact === "negative").slice(0, 3);

  return (
    <div className="min-h-dvh bg-ink-950 bg-[radial-gradient(ellipse_80%_50%_at_50%_-10%,rgba(212, 245, 58,0.10),transparent)]">
      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-ink-950/75 backdrop-blur-xl">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <Brand compact />
          <div className="hidden xl:block">
            <Stepper step={3} />
          </div>
          <div className="flex items-center gap-1.5">
            {onReplay && (
              <button onClick={onReplay} className="flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[11px] text-slate-300 hover:bg-white/[0.06] hover:text-white" title="Replay the agents' investigation on the map">
                <PlayCircle size={14} /> <span className="hidden sm:inline">Replay</span>
              </button>
            )}
            <Link href="/" className="flex items-center gap-1.5 whitespace-nowrap rounded-xl px-2.5 py-1.5 text-[11px] text-slate-300 hover:bg-white/[0.06] hover:text-white">
              <ArrowLeft size={14} /> <span className="hidden sm:inline">Another building</span>
            </Link>
            <Link href={analysis.search_id ? `/compare?search=${encodeURIComponent(analysis.search_id)}` : `/compare?ids=${encodeURIComponent(analysis.id)}`} className="flex items-center gap-1.5 rounded-xl bg-teal-300 px-3 py-1.5 text-[11px] font-semibold text-ink-950 hover:bg-teal-200">
              <Scale size={13} /> Compare
            </Link>
          </div>
        </div>
        {/* Compact score bar once the hero scrolls away */}
        <AnimatePresence>
          {compact && (
            // Overlay just below the sticky header: it must not change layout height, or the page jitters.
            <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.18 }} className="absolute inset-x-0 top-full overflow-hidden border-b border-white/[0.06] bg-ink-950/95 shadow-lg shadow-black/30 backdrop-blur-xl">
              <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-2">
                <ScoreRing value={rec.score} size={34} color={v.color} animateIn={false} />
                <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${v.bg} ${v.text}`}>{rec.label || v.label}</span>
                <span className="hidden min-w-0 flex-1 truncate text-[12px] text-slate-400 sm:block">{title}</span>
                {budget ? (
                  <span className={`ml-auto rounded-full px-2.5 py-0.5 text-[11px] ${BUDGET_UI[budget.status].cls}`}>{budget.source === "user" ? BUDGET_UI[budget.status].label : `${BUDGET_UI[budget.status].label} (typical)`}</span>
                ) : result.costs ? (
                  <span className="ml-auto rounded-full bg-white/[0.05] px-2.5 py-0.5 text-[11px] text-slate-300">{fmtRange(result.costs.upfront.low, result.costs.upfront.high)} upfront</span>
                ) : null}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 px-4 py-6">
        {/* Hero */}
        <motion.section initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} className="grid gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
          <div className="glass relative overflow-hidden rounded-3xl p-5 sm:p-6">
            <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full blur-3xl" style={{ background: `${v.color}22` }} />
            <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center">
              <ScoreRing value={rec.score} size={156} color={v.color} label="suitability" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`flex items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold ${v.bg} ${v.text}`}>
                    <BadgeCheck size={13} /> {rec.label || v.label}
                  </span>
                  <span className="text-[11px] text-slate-500">
                    {result.business_label}
                    {analysis.intent.seats ? ` · ${analysis.intent.seats} seats` : ""}
                    {duration != null ? ` · analyzed in ${fmtClock(duration)}` : ""}
                    {demo ? " · sample" : ""}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ring-1 ring-inset ${
                      analysis.mode === "quick" ? "bg-teal-300/10 text-teal-200 ring-teal-300/30" : "bg-white/[0.04] text-slate-400 ring-white/10"
                    }`}
                    title={analysis.mode === "quick" ? "Quick response: agents started from pre-gathered evidence" : "Deep report: full investigation with follow-ups"}
                  >
                    {analysis.mode === "quick" ? "Quick" : "Deep report"}
                  </span>
                </div>
                <h1 className="mt-2 text-xl font-semibold leading-snug tracking-tight text-slate-50 sm:text-[22px]">{rec.headline}</h1>
                <p className="mt-1.5 flex items-center gap-1.5 truncate text-[12px] text-slate-400">
                  <MapPinned size={12} className="shrink-0 text-teal-300" /> {title}
                </p>
                <div className="mt-4 max-w-sm">
                  <div className="mb-1 flex items-center justify-between text-[11px]">
                    <span className="flex items-center gap-1 text-slate-400">
                      <Gauge size={11} /> Confidence
                    </span>
                    <span className="font-mono text-slate-300">{Math.round(rec.confidence)}%</span>
                  </div>
                  <Meter value={rec.confidence} color="linear-gradient(90deg,#60a5fa,#e2fb5c)" />
                </div>
              </div>
            </div>
            {rec.explanation && (
              <div className="relative mt-5 border-t border-white/[0.06] pt-4">
                <p className={`text-[13px] leading-relaxed text-slate-300 ${expanded ? "" : "line-clamp-2"}`}>{rec.explanation}</p>
                <button onClick={() => setExpanded((e) => !e)} className="mt-1 flex items-center gap-1 text-[11px] text-teal-300 hover:text-teal-200">
                  {expanded ? "Show less" : "Read the full reasoning"} <ChevronDown size={12} className={expanded ? "rotate-180" : ""} />
                </button>
              </div>
            )}
            {rec.dealbreakers.length > 0 && (
              <div className="relative mt-3 rounded-xl bg-rose-500/10 px-3 py-2 text-[12px] text-rose-200 ring-1 ring-inset ring-rose-400/25">Why the verdict is limited: {rec.dealbreakers.join(" · ")}</div>
            )}
          </div>
          <BudgetCard costs={result.costs} />
        </motion.section>

        <RequirementChecks checks={result.requirement_checks ?? []} request={analysis.base_query ?? analysis.query} extra={analysis.extra_requirements ?? null} />

        {/* Pros / cons */}
        <section className="grid gap-3 md:grid-cols-2">
          <ReasonList title="What works" icon={<ThumbsUp size={14} />} color="#34d399" items={pros} empty="No clear strengths recorded." />
          <ReasonList title="What holds it back" icon={<ThumbsDown size={14} />} color="#fb7185" items={cons} empty="No major concerns recorded." />
        </section>

        {/* Tabs */}
        <section className="glass rounded-3xl p-4 sm:p-5">
          <Tabs<Tab>
            layoutId="dash-tab"
            value={tab}
            onChange={setTab}
            className="mb-5"
            tabs={[
              { id: "overview", label: "Checks", icon: <Gauge size={13} /> },
              { id: "needs", label: "Your needs", icon: <ClipboardList size={13} /> },
              { id: "location", label: "Location", icon: <MapPinned size={13} /> },
              ...(p.matterport ? [{ id: "interior" as const, label: "Interior 3D", icon: <Box size={13} /> }] : []),
              { id: "costs", label: "Costs", icon: <CircleDollarSign size={13} /> },
              { id: "compliance", label: "Rules", icon: <Landmark size={13} /> },
              { id: "agents", label: "Agents", icon: <Users size={13} /> },
              { id: "evidence", label: "Evidence", icon: <FileSearch size={13} /> },
            ]}
          />
          <AnimatePresence mode="wait">
            <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.22 }}>
              {tab === "overview" && <MetricsOverview metrics={result.metrics} businessLabel={result.business_label} />}
              {tab === "needs" && <NeedsTab program={result.program} checks={result.site_checks} />}
              {tab === "location" && <LocationTab result={result} property={p} />}
              {tab === "interior" && p.matterport && <InteriorTab link={p.matterport} report={result.agents.find((a) => a.agent === "matterport")} />}
              {tab === "costs" && <CostsTab costs={result.costs} />}
              {tab === "compliance" && <ComplianceTab items={result.compliance} />}
              {tab === "agents" && <AgentsTab agents={result.agents} />}
              {tab === "evidence" && <EvidenceTab result={result} />}
            </motion.div>
          </AnimatePresence>
        </section>

        <section className="glass rounded-3xl px-4 py-1 sm:px-5">
          <div className="pt-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">More details</div>
          <MoreDetails result={result} />
        </section>

        <footer className="pb-10 pt-2 text-center text-[11px] text-slate-600">
          <Building2 size={12} className="mr-1 inline" />
          Scores and costs are computed deterministically from agent findings; narrative by an LLM. Decision support, not legal advice.
        </footer>
      </main>
    </div>
  );
}

function ReasonList({ title, icon, color, items, empty }: { title: string; icon: React.ReactNode; color: string; items: AnalysisResult["recommendation"]["key_reasons"]; empty: string }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <div className="glass rounded-2xl p-4">
      <div className="mb-3 flex items-center gap-2 text-[12px] font-semibold" style={{ color }}>
        {icon} {title}
      </div>
      {items.length === 0 ? (
        <p className="text-xs text-slate-500">{empty}</p>
      ) : (
        <motion.ul variants={stagger.container} initial="hidden" animate="show" className="space-y-2">
          {items.map((r, i) => {
            const [name, ...rest] = r.text.split(":");
            const body = rest.join(":").trim() || r.text;
            const isOpen = open === i;
            return (
              <motion.li key={i} variants={stagger.item}>
                {/* The row toggles; evidence chips are their own buttons, so they sit beside (not inside) the toggle. */}
                <div className="rounded-xl bg-white/[0.03] ring-1 ring-inset ring-white/[0.05] transition hover:bg-white/[0.05]">
                  <button onClick={() => setOpen(isOpen ? null : i)} aria-expanded={isOpen} className="flex w-full items-start gap-2.5 p-3 text-left">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-medium text-slate-100">{rest.length ? name : "Finding"}</div>
                      <p className={`mt-0.5 text-[12px] leading-snug text-slate-400 ${isOpen ? "" : "line-clamp-2"}`}>{body}</p>
                    </div>
                  </button>
                  {isOpen && r.evidence_ids.length > 0 && (
                    <div className="-mt-1.5 pb-3 pl-7 pr-3">
                      <EvidenceChips ids={r.evidence_ids} />
                    </div>
                  )}
                </div>
              </motion.li>
            );
          })}
        </motion.ul>
      )}
    </div>
  );
}

/** Estimate vs budget (the user's, or a typical one when none was given). */
function BudgetCard({ costs }: { costs: Costs | null }) {
  if (!costs) {
    return (
      <div className="glass rounded-3xl p-5">
        <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-300">
          <Wallet size={14} /> Budget
        </div>
        <p className="mt-2 text-xs text-slate-500">No cost estimate was produced for this analysis.</p>
      </div>
    );
  }
  const b = costs.budget;
  const periodLabel = (p: string) => (p === "monthly" ? "per month" : p === "annual" ? "per year" : "upfront");
  if (!b) {
    return (
      <div className="glass flex flex-col rounded-3xl p-5">
        <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-300">
          <Wallet size={14} className="text-amber-300" /> Estimated cost
        </div>
        <div className="mt-3 font-display text-2xl font-semibold tracking-tight text-slate-50">{fmtRange(costs.upfront.low, costs.upfront.high)}</div>
        <div className="text-[11px] text-slate-500">upfront to open</div>
        {costs.monthly_occupancy && (
          <div className="mt-3 text-sm text-slate-200">
            {fmtRange(costs.monthly_occupancy.low, costs.monthly_occupancy.high)} <span className="text-[11px] text-slate-500">per month</span>
          </div>
        )}
        <CostDrivers costs={costs} />
        <p className="mt-auto pt-4 text-[11px] leading-snug text-teal-200/50">
          <span className="rounded bg-teal-300/10 px-1 py-0.5">You didn&apos;t specify a budget</span> — these are typical figures for this kind of business, based on the choices you made.
        </p>
      </div>
    );
  }
  const ui = BUDGET_UI[b.status];
  const max = Math.max(b.amount, b.compare_high) * 1.12;
  const pct = (n: number) => `${(n / max) * 100}%`;
  return (
    <div className="glass flex flex-col rounded-3xl p-5">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[12px] font-semibold text-slate-300">
          <Wallet size={14} style={{ color: ui.color }} /> {b.source === "user" ? "Your budget" : "Typical budget"}
        </div>
        <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${ui.cls}`}>{ui.label}</span>
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <span className="font-display text-2xl font-semibold tracking-tight text-slate-50">{fmtMoney(b.amount)}</span>
        <span className="text-[11px] text-slate-500">{periodLabel(b.period)}</span>
      </div>
      <div className="mt-1 text-[12px] text-slate-400">
        Estimate {fmtRange(b.compare_low, b.compare_high)} {periodLabel(b.period)}
      </div>
      {/* Range vs budget marker */}
      <div className="relative mt-5 h-3 rounded-full bg-white/[0.06]">
        <motion.div
          className="absolute inset-y-0 rounded-full"
          style={{ left: pct(b.compare_low), background: `linear-gradient(90deg, ${ui.color}88, ${ui.color})` }}
          initial={{ width: 0 }}
          animate={{ width: `calc(${pct(b.compare_high)} - ${pct(b.compare_low)})` }}
          transition={{ duration: 1, ease: [0.16, 1, 0.3, 1], delay: 0.3 }}
        />
        <motion.div className="absolute -top-1.5 h-6 w-0.5 rounded bg-white" style={{ left: pct(b.amount) }} initial={{ opacity: 0, scaleY: 0 }} animate={{ opacity: 1, scaleY: 1 }} transition={{ delay: 0.9 }} />
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] text-slate-500">
        <span>$0</span>
        <span>▲ budget</span>
      </div>
      {(costs.budgets ?? []).filter((x) => x.period !== b.period).map((x) => {
        const xu = BUDGET_UI[x.status];
        return (
          <div key={x.period} className="mt-3 flex items-center justify-between gap-2 rounded-xl bg-white/[0.03] px-3 py-2 text-[11px] ring-1 ring-inset ring-white/[0.06]">
            <span className="text-slate-300">
              Also: <span className="font-semibold text-slate-100">{fmtMoney(x.amount)}</span> {periodLabel(x.period)}
              <span className="text-slate-500"> · estimate {fmtRange(x.compare_low, x.compare_high)}</span>
            </span>
            <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${xu.cls}`}>{xu.label}</span>
          </div>
        );
      })}
      {costs.monthly_occupancy && b.period !== "monthly" && (
        <div className="mt-3 text-[12px] text-slate-300">
          {fmtRange(costs.monthly_occupancy.low, costs.monthly_occupancy.high)} <span className="text-[11px] text-slate-500">per month to occupy</span>
        </div>
      )}
      {b.source === "typical" ? (
        <p className="mt-auto pt-4 text-[11px] leading-snug text-teal-200/50">
          <span className="rounded bg-teal-300/10 px-1 py-0.5">You didn&apos;t specify a budget</span> — this compares against an average budget for a business like yours, based on the choices you made.
        </p>
      ) : (
        <p className="mt-auto pt-4 text-[11px] leading-snug text-slate-500">{b.note}</p>
      )}
    </div>
  );
}


/** Biggest fit-out line items as small animated bars (fills the cost card when there is no budget bar). */
function CostDrivers({ costs }: { costs: NonNullable<AnalysisResult["costs"]> }) {
  const items = [...costs.fitout.line_items].sort((a, b) => b.high - a.high).slice(0, 4);
  const max = Math.max(...items.map((i) => i.high), 1);
  if (!items.length) return null;
  return (
    <div className="mt-5">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Biggest cost drivers</div>
      <ul className="space-y-2.5">
        {items.map((it, i) => (
          <li key={it.id}>
            <div className="flex items-baseline justify-between gap-3 text-[11px]">
              <span className="truncate text-slate-300">{it.label.replace(/\s*\(.*\)$/, "")}</span>
              <span className="shrink-0 font-mono text-slate-400">{fmtRange(it.low, it.high)}</span>
            </div>
            <div className="relative mt-1 h-1.5 rounded-full bg-white/[0.06]">
              <motion.div
                className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-teal-300/40 to-teal-300"
                initial={{ width: 0 }}
                animate={{ width: `${(it.high / max) * 100}%` }}
                transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1], delay: 0.2 + i * 0.08 }}
              />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}


const REQ_UI = {
  met: { label: "Met", cls: "bg-emerald-400/10 text-emerald-300 ring-emerald-300/30", dot: "#34d399" },
  unmet: { label: "Not met", cls: "bg-rose-400/10 text-rose-300 ring-rose-300/30", dot: "#fb7185" },
  unknown: { label: "Unverified", cls: "bg-white/[0.04] text-slate-400 ring-white/10", dot: "#64748b" },
} as const;

/** The user's own stated needs (search + extra requirements), each met / not met / unverified, expandable. */
/** The user's request (search prompt + extra requirements) and how each stated need was judged. These checks
 *  count toward the score and an unmet one caps the verdict. */
function RequirementChecks({ checks, request, extra }: { checks: NonNullable<AnalysisResult["requirement_checks"]>; request: string; extra: string | null }) {
  const [open, setOpen] = useState<string | null>(null);
  const current = checks.find((c) => c.requirement === open);
  return (
    <section className="glass rounded-3xl p-4 sm:p-5">
      <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold text-slate-300">
        <BadgeCheck size={14} className="text-teal-300" /> Your request
        <span className="font-normal text-slate-500">· what this analysis was judged against</span>
      </div>
      <p className="text-[13px] leading-relaxed text-slate-200">“{request}”</p>
      {extra && <p className="mt-1 text-[12px] text-slate-400">Extra requirements: {extra}</p>}
      {checks.length === 0 ? (
        <p className="mt-2 text-[11px] text-slate-500">No specific needs were picked out of your request, so it was judged on the standard checks for this business.</p>
      ) : (
        <p className="mb-2 mt-3 text-[11px] text-slate-500">Each need below counts toward the score; an unmet one caps the verdict.</p>
      )}
      <div className="flex flex-wrap gap-2">
        {checks.map((c) => {
          const ui = REQ_UI[c.status];
          const on = open === c.requirement;
          return (
            <button
              key={c.requirement}
              onClick={() => setOpen(on ? null : c.requirement)}
              aria-expanded={on}
              className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-[12px] ring-1 ring-inset transition ${ui.cls} ${on ? "ring-2" : "hover:brightness-125"}`}
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: ui.dot }} />
              <span className="capitalize text-slate-100">{c.requirement}</span>
              <span className="text-[10px] font-semibold uppercase tracking-wider">{ui.label}</span>
            </button>
          );
        })}
      </div>
      <AnimatePresence initial={false}>
        {current && (
          <motion.div
            key={current.requirement}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="mt-3 rounded-2xl bg-white/[0.03] p-3 text-[12px] leading-relaxed text-slate-300 ring-1 ring-inset ring-white/[0.06]">
              {current.rationale}
              {current.evidence_ids.length > 0 && (
                <div className="mt-2">
                  <EvidenceChips ids={current.evidence_ids} />
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
