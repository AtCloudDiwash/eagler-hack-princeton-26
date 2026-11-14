"use client";

import type { AnalysisResult, PropertyDetail } from "@/lib/api-types";
import { VERDICT_STYLE } from "@/lib/format";
import { Card, Meter, Pill, ScoreRing } from "@/components/ui/primitives";
import { EvidenceChips } from "./EvidenceContext";

export default function VerdictHero({ result, property }: { result: AnalysisResult; property: PropertyDetail }) {
  const rec = result.recommendation;
  const v = VERDICT_STYLE[rec.verdict];
  const positives = rec.key_reasons.filter((r) => r.impact === "positive");
  const negatives = rec.key_reasons.filter((r) => r.impact === "negative");
  const known = result.metrics.filter((m) => m.status !== "unknown").length;

  return (
    <Card className="relative overflow-hidden p-5 sm:p-6">
      <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full blur-3xl" style={{ background: `${v.color}1f` }} />
      <div className="relative grid gap-6 lg:grid-cols-[auto_1fr]">
        <div className="flex flex-row items-center gap-5 lg:flex-col lg:items-center">
          <ScoreRing value={rec.score} color={v.color} label="suitability" size={148} />
          <div className="w-full min-w-[140px] max-w-[180px]">
            <div className="mb-1 flex justify-between text-[11px]">
              <span className="text-slate-400">Confidence</span>
              <span className="font-mono text-slate-200">{Math.round(rec.confidence)}%</span>
            </div>
            <Meter value={rec.confidence} color="#60a5fa" className="h-2" />
            <p className="mt-1.5 text-[10px] leading-snug text-slate-500">
              {known}/{result.metrics.length} metrics backed by evidence
            </p>
          </div>
        </div>

        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded-full px-3 py-1 text-xs font-bold ring-1 ${v.bg} ${v.text} ${v.ring}`}>{rec.label || v.label}</span>
            <Pill className="bg-ink-700/60 text-slate-300 ring-line">{result.business_label}</Pill>
            {property.building_type && <Pill className="bg-ink-700/60 text-slate-300 ring-line">{property.building_type.replace(/_/g, " ")}</Pill>}
          </div>
          <h1 className="mt-3 text-xl font-semibold leading-snug text-slate-50 sm:text-2xl">{rec.headline}</h1>
          <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-300">{rec.explanation}</p>

          {rec.dealbreakers.length > 0 && (
            <div className="mt-4 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3">
              <div className="mb-1 text-[10px] font-bold uppercase tracking-[0.16em] text-rose-300">Dealbreakers</div>
              <ul className="space-y-1 text-sm text-rose-100">
                {rec.dealbreakers.map((d, i) => (
                  <li key={i}>⛔ {d}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <ReasonList title="Why it works" items={positives} tone="pos" />
            <ReasonList title="What holds it back" items={negatives} tone="neg" />
          </div>
        </div>
      </div>
    </Card>
  );
}

function ReasonList({ title, items, tone }: { title: string; items: AnalysisResult["recommendation"]["key_reasons"]; tone: "pos" | "neg" }) {
  return (
    <div className={`rounded-xl border p-3 ${tone === "pos" ? "border-emerald-500/25 bg-emerald-500/5" : "border-amber-500/25 bg-amber-500/5"}`}>
      <div className={`mb-2 text-[10px] font-bold uppercase tracking-[0.16em] ${tone === "pos" ? "text-emerald-300" : "text-amber-300"}`}>{title}</div>
      {items.length === 0 ? (
        <p className="text-xs text-slate-500">None identified.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((r, i) => (
            <li key={i} className="flex gap-2 text-[13px] leading-snug text-slate-200">
              <span className={tone === "pos" ? "text-emerald-400" : "text-amber-400"}>{tone === "pos" ? "+" : "−"}</span>
              <span>
                {r.text} <EvidenceChips ids={r.evidence_ids} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
