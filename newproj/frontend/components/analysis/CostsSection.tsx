"use client";

import type { Costs } from "@/lib/api-types";
import { fmtMoney, fmtRange } from "@/lib/format";
import { Card, Collapsible, EmptyNote, RangeBar, SectionTitle } from "@/components/ui/primitives";
import { EvidenceChips } from "./EvidenceContext";

export default function CostsSection({ costs }: { costs: Costs | null }) {
  if (!costs) {
    return (
      <section>
        <SectionTitle id="costs" eyebrow="Financial" title="Financial feasibility" />
        <EmptyNote>The cost agent did not produce an estimate.</EmptyNote>
      </section>
    );
  }
  const max = Math.max(1, ...costs.fitout.line_items.map((l) => l.high));
  return (
    <section>
      <SectionTitle id="costs" eyebrow="Financial" title="Financial feasibility" />
      <div className="grid gap-3 sm:grid-cols-3">
        <BigNumber label="Upfront (fit-out + deposits)" value={fmtRange(costs.upfront.low, costs.upfront.high)} accent="#fbbf24" />
        <BigNumber
          label="Monthly occupancy"
          value={costs.monthly_occupancy ? fmtRange(costs.monthly_occupancy.low, costs.monthly_occupancy.high) : "—"}
          sub="rent + NNN + amortized fit-out"
          accent="#2dd4bf"
        />
        <BigNumber
          label="Base rent / year"
          value={costs.rent ? fmtRange(costs.rent.low_annual, costs.rent.high_annual) : "Unavailable"}
          sub={costs.rent ? `$${costs.rent.per_sqft_low}–${costs.rent.per_sqft_high}/sq ft · ${costs.rent.source}` : "No rent data for this property"}
          accent="#a78bfa"
        />
      </div>

      <Card className="mt-3 p-4">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-semibold text-slate-100">Fit-out estimate · {fmtRange(costs.fitout.low, costs.fitout.high)}</h3>
          <span className="text-[11px] text-slate-500">
            {costs.sqft_used ? `${costs.sqft_used.toLocaleString()} sq ft` : "size unknown"} · {costs.sqft_basis}
          </span>
        </div>
        <div className="space-y-3">
          {costs.fitout.line_items.map((l) => (
            <div key={l.id} className="grid grid-cols-1 gap-1 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto] sm:items-center sm:gap-3">
              <div className="min-w-0">
                <div className="text-[13px] text-slate-200">{l.label}</div>
                <div className="text-[11px] leading-snug text-slate-500">
                  {l.reason} <EvidenceChips ids={l.evidence_ids} />
                </div>
              </div>
              <RangeBar low={l.low} high={l.high} max={max} color="#fbbf24" />
              <div className="font-mono text-[11px] text-slate-300 sm:w-32 sm:text-right">{fmtRange(l.low, l.high)}</div>
            </div>
          ))}
        </div>
        <div className="mt-2 flex justify-between text-[10px] text-slate-600">
          <span>$0</span>
          <span>{fmtMoney(max)}</span>
        </div>
        {costs.assumptions.length > 0 && (
          <div className="mt-3">
            <Collapsible title="Assumptions & method" count={costs.assumptions.length}>
              <ul className="list-disc space-y-1 pl-5 text-[12px] text-slate-400">
                {costs.assumptions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </Collapsible>
          </div>
        )}
      </Card>
    </section>
  );
}

function BigNumber({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent: string }) {
  return (
    <Card className="relative overflow-hidden p-4">
      <div className="absolute inset-y-0 left-0 w-1" style={{ background: accent }} />
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-xl font-semibold text-slate-50">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] leading-snug text-slate-500">{sub}</div>}
    </Card>
  );
}
