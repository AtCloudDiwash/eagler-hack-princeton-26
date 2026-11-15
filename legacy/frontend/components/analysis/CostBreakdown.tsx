import { formatCompactCurrency, formatCurrency, formatNumber, formatRange, humanize } from "@/lib/format";
import type { AnalysisResult } from "@/lib/types";

/**
 * min/max on a line item are totals (band x qty). Large quantities are square footage for per-sq-ft
 * items, so the "x qty" hint is only shown for small counts (same rule as the backend's letter).
 *
 * Line items (with reasons) from the rule-based cost engine, then any breakdown entries that are not
 * line items (soft costs such as permits, design, contingency), then the roll-up to cost to open.
 */
export function CostBreakdown({ result }: { result: AnalysisResult }) {
  const lineItems = result.line_items ?? [];
  const lineItemIds = new Set(lineItems.map((li) => li.item));
  const softCosts = Object.entries(result.breakdown ?? {}).filter(([key]) => !lineItemIds.has(key));

  return (
    <div className="grid gap-4 text-sm">
      {lineItems.length === 0 && softCosts.length === 0 && <p className="text-ink-muted">No cost items: N/A</p>}

      {lineItems.length > 0 && (
        <ul className="divide-y divide-line">
          {lineItems.map((li) => (
            <li key={li.item} className="grid gap-0.5 py-2.5 first:pt-0">
              <div className="flex items-baseline justify-between gap-3">
                <span className="font-medium">
                  {li.label || humanize(li.item)}
                  {li.qty > 1 && li.qty < 100 && <span className="text-ink-muted"> × {formatNumber(li.qty)}</span>}
                </span>
                <span className="shrink-0 tabular-nums">{formatRange({ min: li.min, max: li.max })}</span>
              </div>
              <p className="text-xs text-ink-muted">{li.reason || "N/A"}</p>
            </li>
          ))}
        </ul>
      )}

      {softCosts.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-ink-muted">Soft costs &amp; other</p>
          <ul className="grid gap-1">
            {softCosts.map(([key, range]) => (
              <li key={key} className="flex justify-between gap-3">
                <span>{humanize(key)}</span>
                <span className="tabular-nums">{formatRange(range)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <dl className="grid gap-1 rounded-lg border border-line bg-navy-900/60 p-3">
        <div className="flex justify-between gap-3">
          <dt className="text-ink-muted">Fit-out (gross)</dt>
          <dd className="tabular-nums">{formatRange(result.fit_out_estimate)}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-ink-muted">Less TI allowance</dt>
          <dd className="tabular-nums text-pass">
            {result.ti_allowance > 0 ? `−${formatCompactCurrency(result.ti_allowance)}` : formatCurrency(result.ti_allowance)}
          </dd>
        </div>
        <div className="flex justify-between gap-3 border-t border-line pt-1.5 font-semibold">
          <dt>Cost to open</dt>
          <dd className="tabular-nums text-accent">{formatRange(result.total_cost_estimate)}</dd>
        </div>
        <p className="text-xs text-ink-muted">Net fit-out plus rent paid during build-out.</p>
      </dl>
    </div>
  );
}
