import { NoSymbolIcon } from "@heroicons/react/20/solid";
import type { ReactNode } from "react";
import { formatCompactCurrency, formatMonths, formatPercent, formatRange, formatRent, formatValue, humanize, orNA } from "@/lib/format";
import type { AnalysisResult } from "@/lib/types";
import { Badge } from "../ui/Badge";
import { Card, SectionTitle } from "../ui/Card";
import { CostBreakdown } from "./CostBreakdown";
import { CriteriaResults } from "./CriteriaResults";
import { LandlordLetter } from "./LandlordLetter";
import { MediaPanel } from "./MediaPanel";
import { ScoreRing } from "./ScoreRing";

function KeyNumber({ label, value, emphasis = false }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className="rounded-lg border border-line bg-navy-900/60 px-3 py-2">
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className={`text-sm font-semibold tabular-nums sm:text-base ${emphasis ? "text-accent" : ""}`}>{value}</dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="min-w-0">
      <SectionTitle>{title}</SectionTitle>
      {children}
    </section>
  );
}

/** Full report for one property: numbers, costs, criteria, evidence overlays, landlord materials. */
export function AnalysisCard({ result }: { result: AnalysisResult }) {
  const descriptions = new Map((result.criteria_results ?? []).map((c) => [c.id, c.description]));
  const observations = Object.entries(result.observations ?? {});

  return (
    <Card id={`result-${result.property_id}`} className="scroll-mt-20 overflow-hidden" data-testid="analysis-card">
      <header className="flex items-start gap-4 border-b border-line p-4 sm:p-5">
        <ScoreRing score={result.score} disqualified={result.disqualified} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent">Rank #{result.rank}</Badge>
            {result.disqualified && (
              <Badge tone="danger">
                <NoSymbolIcon className="size-3" aria-hidden /> Disqualified
              </Badge>
            )}
          </div>
          <h2 className="mt-1 text-lg font-semibold leading-snug sm:text-xl">{result.address}</h2>
          <p className="font-mono text-xs text-ink-muted">{result.property_id}</p>
        </div>
      </header>

      <div className="grid gap-8 p-4 sm:p-5">
        {result.disqualified && (
          <div role="alert" className="rounded-lg border border-red-400/40 bg-red-400/10 p-3 text-sm">
            <p className="font-medium text-red-300">Blocked by a hard requirement:</p>
            <ul className="mt-1 list-inside list-disc text-ink-muted">
              {(result.disqualifiers.length ? result.disqualifiers : ["unspecified"]).map((id) => (
                <li key={id}>{descriptions.get(id) ?? humanize(id)}</li>
              ))}
            </ul>
          </div>
        )}

        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <KeyNumber label="Cost to open" value={formatRange(result.total_cost_estimate)} emphasis />
          <KeyNumber label="First-year cost" value={formatRange(result.first_year_cost)} />
          <KeyNumber label="Monthly rent" value={formatRent(result.monthly_rent)} />
          <KeyNumber label="Build-out" value={formatMonths(result.buildout_months)} />
          <KeyNumber label="Fit-out (gross)" value={formatRange(result.fit_out_estimate)} />
          <KeyNumber label="TI allowance" value={formatCompactCurrency(result.ti_allowance)} />
        </dl>

        <div className="grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <Section title="Cost breakdown">
            <CostBreakdown result={result} />
          </Section>
          <Section title="Visual evidence">
            <MediaPanel result={result} />
          </Section>
        </div>

        <Section title="Compliance & criteria">
          <CriteriaResults result={result} />
        </Section>

        <div className="grid gap-8 lg:grid-cols-2">
          <Section title="Questions for the landlord">
            {result.questions_for_landlord?.length ? (
              <ol className="mb-4 list-inside list-decimal space-y-1.5 text-sm">
                {result.questions_for_landlord.map((question, index) => (
                  <li key={index}>{question}</li>
                ))}
              </ol>
            ) : (
              <p className="mb-4 text-sm text-ink-muted">N/A</p>
            )}
            <LandlordLetter letter={result.landlord_request} />
          </Section>

          <div className="grid content-start gap-8">
            <Section title="Observations">
              {observations.length ? (
                <ul className="divide-y divide-line text-sm">
                  {observations.map(([key, evidence]) => (
                    <li key={key} className="grid gap-0.5 py-2 first:pt-0">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <span className="font-medium">{humanize(key)}</span>
                        <span className="tabular-nums">{formatValue(evidence?.value)}</span>
                      </div>
                      <p className="text-xs text-ink-muted">
                        <span className="uppercase">{evidence?.source ?? "N/A"}</span>
                        {" · "}
                        {evidence?.confidence !== null && evidence?.confidence !== undefined
                          ? `${formatPercent(evidence.confidence)} confidence`
                          : "confidence N/A"}
                        {evidence?.note && <> · {evidence.note}</>}
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-ink-muted">N/A</p>
              )}
            </Section>
            <Section title="Assumptions">
              {result.assumptions?.length ? (
                <ul className="list-inside list-disc space-y-1 text-sm text-ink-muted">
                  {result.assumptions.map((assumption, index) => (
                    <li key={index}>{orNA(assumption)}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-ink-muted">N/A</p>
              )}
            </Section>
          </div>
        </div>
      </div>
    </Card>
  );
}
