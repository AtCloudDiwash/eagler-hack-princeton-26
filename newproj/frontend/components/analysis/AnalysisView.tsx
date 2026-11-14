"use client";

import Link from "next/link";
import { useState } from "react";
import type { Analysis } from "@/lib/api-types";
import { fmtSqft, titleCase } from "@/lib/format";
import { Brand } from "@/components/HealthBadge";
import { Pill } from "@/components/ui/primitives";
import AgentTimeline from "./AgentTimeline";
import AgentReports from "./AgentReports";
import ComplianceTable from "./ComplianceTable";
import CostsSection from "./CostsSection";
import { EvidenceProvider } from "./EvidenceContext";
import MetricsGrid from "./MetricsGrid";
import NeighborhoodSection from "./NeighborhoodSection";
import { ConflictsAndFollowups, DataSources, EvidenceExplorer, RisksAndQuestions } from "./RisksAndSources";
import VerdictHero from "./VerdictHero";

const NAV = [
  ["overview", "Overview"],
  ["metrics", "Metrics"],
  ["neighborhood", "Neighborhood"],
  ["compliance", "Compliance"],
  ["costs", "Costs"],
  ["agents", "Agents"],
  ["risks", "Risks"],
  ["evidence", "Evidence"],
] as const;

/** Header + either the live investigation or the full decision dashboard. */
export default function AnalysisView({ analysis, demo = false }: { analysis: Analysis; demo?: boolean }) {
  const done = analysis.status === "completed" && analysis.result;
  const [tab, setTab] = useState<"dashboard" | "log">("dashboard");
  const showLog = !done || tab === "log";
  const p = analysis.property;

  return (
    <EvidenceProvider evidence={analysis.result?.evidence ?? []}>
      <div className="min-h-dvh bg-ink-950">
        <header className="sticky top-0 z-[2000] border-b border-line bg-ink-950/85 backdrop-blur">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
            <Link href="/">
              <Brand />
            </Link>
            <div className="flex items-center gap-2">
              <Link href="/" className="rounded-lg border border-line px-3 py-1.5 text-xs text-slate-300 hover:border-teal-400 hover:text-teal-300">
                ← Investigate another building
              </Link>
              <Link
                href={`/compare?ids=${encodeURIComponent(analysis.id)}`}
                className="rounded-lg bg-teal-500 px-3 py-1.5 text-xs font-semibold text-ink-950 hover:bg-teal-400"
              >
                Compare
              </Link>
            </div>
          </div>
          {done && (
            <nav className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-2 text-[12px]">
              <button
                onClick={() => setTab("dashboard")}
                className={`shrink-0 rounded-lg px-2.5 py-1 ${tab === "dashboard" ? "bg-ink-800 text-teal-300" : "text-slate-400 hover:text-slate-200"}`}
              >
                Decision dashboard
              </button>
              <button
                onClick={() => setTab("log")}
                className={`shrink-0 rounded-lg px-2.5 py-1 ${tab === "log" ? "bg-ink-800 text-teal-300" : "text-slate-400 hover:text-slate-200"}`}
              >
                Investigation log · {analysis.events.length}
              </button>
              {tab === "dashboard" && <span className="mx-1 w-px shrink-0 bg-line" />}
              {tab === "dashboard" &&
                NAV.map(([id, label]) => (
                  <a key={id} href={`#${id}`} className="shrink-0 rounded-lg px-2 py-1 text-slate-500 hover:text-slate-200">
                    {label}
                  </a>
                ))}
            </nav>
          )}
        </header>

        <main className="mx-auto max-w-7xl space-y-8 px-4 py-6">
          <div id="overview" className="flex scroll-mt-28 flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                Analysis {demo ? "· sample data" : `· ${new Date(analysis.created_at).toLocaleString()}`}
              </div>
              <h1 className="mt-1 text-lg font-semibold text-slate-100">{p.address || `${titleCase(p.building_type) || "Building"} · ${fmtSqft(p.area_sqft)}`}</h1>
              <p className="mt-0.5 text-sm text-slate-400">
                “{analysis.query}” <span className="text-slate-600">· radius {analysis.radius_m} m</span>
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Pill className="bg-ink-800 text-slate-300 ring-line">{analysis.intent.business_label}</Pill>
              {analysis.intent.seats != null && <Pill className="bg-ink-800 text-slate-300 ring-line">{analysis.intent.seats} seats</Pill>}
              <Pill className="bg-ink-800 text-slate-300 ring-line">{fmtSqft(p.area_sqft)}</Pill>
              <Pill className="bg-ink-800 text-slate-300 ring-line">{p.source}</Pill>
              {demo && <Pill className="bg-amber-500/15 text-amber-300 ring-amber-400/30">demo</Pill>}
            </div>
          </div>

          {showLog && <AgentTimeline analysis={analysis} />}

          {done && tab === "dashboard" && analysis.result && (
            <>
              <VerdictHero result={analysis.result} property={p} />
              <MetricsGrid metrics={analysis.result.metrics} businessLabel={analysis.result.business_label} />
              <NeighborhoodSection result={analysis.result} property={p} />
              <div className="grid gap-8 xl:grid-cols-2">
                <ComplianceTable items={analysis.result.compliance} />
                <CostsSection costs={analysis.result.costs} />
              </div>
              <AgentReports agents={analysis.result.agents} />
              <RisksAndQuestions result={analysis.result} />
              <ConflictsAndFollowups result={analysis.result} />
              <DataSources result={analysis.result} />
              <EvidenceExplorer result={analysis.result} />
              <footer className="pb-10 pt-4 text-center text-[11px] text-slate-600">
                Scores and costs are computed deterministically from agent findings; narrative by a local LLM. Decision support only.
              </footer>
            </>
          )}
        </main>
      </div>
    </EvidenceProvider>
  );
}
