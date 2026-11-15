import { NoSymbolIcon, TrophyIcon } from "@heroicons/react/16/solid";
import type { ReactNode } from "react";
import { formatCompactCurrency, formatMonths, formatRange, formatRent } from "@/lib/format";
import type { AiSummary, AnalysisResult } from "@/lib/types";
import { Badge } from "../ui/Badge";
import { aiSentenceFor } from "./AiSummaryPanel";
import { WeakFitBadge } from "./WeakFitBadge";

interface Row {
  label: string;
  render: (result: AnalysisResult, minScore?: number) => ReactNode;
}

const ROWS: Row[] = [
  {
    label: "Rank",
    render: (r, minScore) => (
      <span className="inline-flex items-center gap-2">
        #{r.rank}
        <WeakFitBadge weakFit={r.weak_fit} minScore={minScore} />
      </span>
    ),
  },
  { label: "Fit score", render: (r) => `${Math.round(r.score)} / 100` },
  { label: "Cost to open", render: (r) => <span className="font-semibold text-accent">{formatRange(r.total_cost_estimate)}</span> },
  { label: "First-year cost", render: (r) => formatRange(r.first_year_cost) },
  { label: "Monthly rent", render: (r) => formatRent(r.monthly_rent) },
  { label: "Build-out", render: (r) => formatMonths(r.buildout_months) },
  { label: "TI allowance", render: (r) => formatCompactCurrency(r.ti_allowance) },
  {
    label: "Status",
    render: (r) =>
      r.disqualified ? (
        <Badge tone="danger" title={r.disqualifiers.join(", ")}>
          <NoSymbolIcon className="size-3" aria-hidden /> Disqualified
        </Badge>
      ) : (
        <Badge tone="pass">Eligible</Badge>
      ),
  },
];

/**
 * One column per property, sorted by rank. Only this table scrolls horizontally on small screens.
 * `minScore` (AnalyzeResponse.min_score) feeds the "Weak fit" explanation.
 * With an `aiSummary` that covers at least one property, a final "Why" row shows its one-liners.
 */
export function ComparisonTable({
  results,
  minScore,
  aiSummary,
}: {
  results: AnalysisResult[];
  minScore?: number;
  aiSummary?: AiSummary | null;
}) {
  const sorted = [...results].sort((a, b) => a.rank - b.rank);
  const rows = sorted.some((r) => aiSentenceFor(aiSummary, r.property_id))
    ? [
        ...ROWS,
        {
          label: "Why (AI)",
          render: (r: AnalysisResult) => (
            <span className="block max-w-64 whitespace-normal text-xs leading-snug text-ink-muted">
              {aiSentenceFor(aiSummary, r.property_id) ?? "N/A"}
            </span>
          ),
        },
      ]
    : ROWS;
  // Weak fits are never "best value"; if every eligible space is weak, no column is highlighted.
  const best = sorted.find((r) => !r.disqualified && !r.weak_fit);

  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-surface">
      <table className="w-full min-w-max border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className="sticky left-0 z-10 bg-surface px-4 py-3 text-xs font-medium uppercase tracking-wider text-ink-muted">
              Property
            </th>
            {sorted.map((r) => (
              <th
                key={r.property_id}
                scope="col"
                className={`min-w-44 px-4 py-3 align-bottom font-semibold ${r === best ? "bg-accent/5" : ""}`}
              >
                {r === best && (
                  <span className="mb-1 flex items-center gap-1 text-xs font-medium text-accent">
                    <TrophyIcon className="size-3.5" aria-hidden /> Best value
                  </span>
                )}
                <a href={`#result-${r.property_id}`} className="hover:text-accent hover:underline">
                  {r.address}
                </a>
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row) => (
            <tr key={row.label}>
              <th scope="row" className="sticky left-0 z-10 bg-surface px-4 py-2.5 text-xs font-medium text-ink-muted">
                {row.label}
              </th>
              {sorted.map((r) => (
                <td key={r.property_id} className={`px-4 py-2.5 tabular-nums ${r === best ? "bg-accent/5" : ""}`}>
                  {row.render(r, minScore)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
