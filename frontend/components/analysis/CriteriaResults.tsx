import { NoSymbolIcon } from "@heroicons/react/16/solid";
import { formatPercent, formatValue, humanize, orNA } from "@/lib/format";
import type { AnalysisResult, ComplianceEntry, CriterionResult, Evidence, Status } from "@/lib/types";
import { Badge, StatusBadge } from "../ui/Badge";
import { InfoTip } from "../ui/InfoTip";
import { LiveDot } from "../ui/LiveDot";

const STATUS_ORDER: Status[] = ["PASS", "RISK", "UNKNOWN"];

/** Groups items by domain, keeping the order in which domains first appear (registry order). */
export function groupByDomain<T extends { domain: string }>(items: T[]): Array<[string, T[]]> {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const domain = item.domain || "other";
    groups.set(domain, [...(groups.get(domain) ?? []), item]);
  }
  return [...groups.entries()];
}

function EvidenceChip({ evidence }: { evidence: Evidence }) {
  const confidence = evidence.confidence !== null ? ` · ${formatPercent(evidence.confidence)}` : "";
  return (
    <span
      className="inline-flex max-w-full items-center gap-1 rounded-md border border-line bg-navy-900 px-1.5 py-0.5 text-[11px] text-ink-muted"
      title={evidence.note ?? undefined}
    >
      <span className="truncate">
        {humanize(evidence.key)}: <span className="text-ink">{formatValue(evidence.value)}</span>
      </span>
      <span className="shrink-0 uppercase">· {evidence.source}{confidence}</span>
      <LiveDot live={evidence.live} />
    </span>
  );
}

function CriterionRow({ criterion }: { criterion: CriterionResult }) {
  return (
    <li data-testid="criterion-result" className="grid gap-1.5 py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={criterion.status} />
        <span className="min-w-0 flex-1 font-medium">{criterion.description || humanize(criterion.id)}</span>
        <InfoTip label={`Source for ${criterion.id}`}>
          <strong>Source:</strong> {orNA(criterion.source)}
        </InfoTip>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
        <span>Weight {criterion.weight}</span>
        {criterion.score !== null && <span>· Score {formatPercent(criterion.score)}</span>}
        {!criterion.counted && <Badge>Not scored</Badge>}
        {criterion.blocking ? (
          <Badge tone="danger">
            <NoSymbolIcon className="size-3" aria-hidden /> Blocking
          </Badge>
        ) : (
          criterion.hard_block && <Badge>Hard block if failed</Badge>
        )}
      </div>
      <p className="text-sm text-ink-muted">{orNA(criterion.notes)}</p>
      {criterion.evidence?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {criterion.evidence.map((evidence, index) => (
            <EvidenceChip key={`${evidence.key}-${index}`} evidence={evidence} />
          ))}
        </div>
      )}
    </li>
  );
}

function ComplianceRow({ id, entry }: { id: string; entry: ComplianceEntry }) {
  return (
    <li data-testid="compliance-extra" className="grid gap-1.5 py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={entry.status} />
        <span className="min-w-0 flex-1 font-medium">{humanize(id)}</span>
        <InfoTip label={`Source for ${id}`}>
          <strong>Source:</strong> {orNA(entry.source)}
        </InfoTip>
      </div>
      <p className="text-sm text-ink-muted">{orNA(entry.notes)}</p>
    </li>
  );
}

/** Criteria results grouped by domain, plus any compliance entries not already covered by a criterion. */
export function CriteriaResults({ result }: { result: AnalysisResult }) {
  const criteria = result.criteria_results ?? [];
  const covered = new Set(criteria.map((c) => c.id));
  const extraCompliance = Object.entries(result.compliance ?? {}).filter(([id]) => !covered.has(id));
  const counts = STATUS_ORDER.map((status) => ({
    status,
    count:
      criteria.filter((c) => c.status === status).length +
      extraCompliance.filter(([, entry]) => entry.status === status).length,
  }));

  if (criteria.length === 0 && extraCompliance.length === 0) {
    return <p className="text-sm text-ink-muted">No criteria were evaluated: N/A</p>;
  }

  return (
    <div className="grid gap-4">
      <p className="flex flex-wrap gap-3 text-xs text-ink-muted">
        {counts.map(({ status, count }) => (
          <span key={status}>
            <span className="font-semibold text-ink">{count}</span> {status}
          </span>
        ))}
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        {groupByDomain(criteria).map(([domain, items]) => (
          <section key={domain} className="rounded-lg border border-line bg-navy-900/40 p-3">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-accent">{humanize(domain)}</h4>
            <ul className="divide-y divide-line">
              {items.map((criterion) => (
                <CriterionRow key={criterion.id} criterion={criterion} />
              ))}
            </ul>
          </section>
        ))}
        {extraCompliance.length > 0 && (
          <section className="rounded-lg border border-line bg-navy-900/40 p-3">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-accent">Other compliance checks</h4>
            <ul className="divide-y divide-line">
              {extraCompliance.map(([id, entry]) => (
                <ComplianceRow key={id} id={id} entry={entry} />
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
