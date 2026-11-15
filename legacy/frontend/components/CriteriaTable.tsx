import { NoSymbolIcon } from "@heroicons/react/16/solid";
import { humanize, orNA } from "@/lib/format";
import type { Criterion } from "@/lib/types";
import { Badge } from "./ui/Badge";
import { InfoTip } from "./ui/InfoTip";

/**
 * Renders whatever the criteria registry returns (GET /api/v1/criteria). Nothing here knows about
 * specific criterion ids: adding a criterion in backend/criteria.yaml adds a row automatically.
 */
export function CriteriaTable({ criteria }: { criteria: Criterion[] }) {
  if (criteria.length === 0) {
    return <p className="text-sm text-ink-muted">No criteria apply to this business type and location.</p>;
  }
  const totalWeight = criteria.reduce((sum, c) => sum + (Number.isFinite(c.weight) ? c.weight : 0), 0);

  return (
    <div className="overflow-hidden rounded-lg border border-line">
      <table className="w-full text-left text-sm">
        <thead className="bg-surface-raised text-xs uppercase tracking-wider text-ink-muted">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Criterion</th>
            <th scope="col" className="hidden px-3 py-2 font-medium md:table-cell">Domain</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Weight</th>
            <th scope="col" className="px-3 py-2 font-medium">Hard block</th>
            <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">Source</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {criteria.map((criterion) => (
            <tr key={criterion.id} data-testid="criterion-row" className="align-top">
              <td className="px-3 py-2.5">
                <div className="flex items-start gap-1.5">
                  <div className="min-w-0">
                    <p className="font-medium">{criterion.description || humanize(criterion.id)}</p>
                    <p className="font-mono text-xs text-ink-muted">{criterion.id}</p>
                    <p className="mt-1 text-xs text-ink-muted md:hidden">{humanize(criterion.domain)}</p>
                  </div>
                  <InfoTip label={`Details for ${criterion.id}`}>
                    <span className="block"><strong>Source:</strong> {orNA(criterion.source)}</span>
                    <span className="block"><strong>Evaluator:</strong> {orNA(criterion.evaluator)}</span>
                    <span className="block">
                      <strong>Inputs:</strong> {criterion.required_inputs?.length ? criterion.required_inputs.join(", ") : "N/A"}
                    </span>
                    <span className="block"><strong>If data is missing:</strong> {humanize(criterion.missing_data_policy ?? "unknown")}</span>
                    <span className="block">
                      <strong>Jurisdictions:</strong>{" "}
                      {criterion.applicable_jurisdictions?.length ? criterion.applicable_jurisdictions.join(", ") : "All"}
                    </span>
                  </InfoTip>
                </div>
              </td>
              <td className="hidden px-3 py-2.5 md:table-cell">
                <Badge>{humanize(criterion.domain)}</Badge>
              </td>
              <td className="px-3 py-2.5 text-right tabular-nums">
                {criterion.weight}
                {totalWeight > 0 && (
                  <span className="block text-xs text-ink-muted">{Math.round((criterion.weight / totalWeight) * 100)}%</span>
                )}
              </td>
              <td className="px-3 py-2.5">
                {criterion.hard_block ? (
                  <Badge tone="danger">
                    <NoSymbolIcon className="size-3" aria-hidden /> Yes
                  </Badge>
                ) : (
                  <span className="text-ink-muted">No</span>
                )}
              </td>
              <td className="hidden max-w-xs px-3 py-2.5 text-xs text-ink-muted lg:table-cell">{orNA(criterion.source)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
