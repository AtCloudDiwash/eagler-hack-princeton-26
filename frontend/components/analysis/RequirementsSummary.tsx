import { formatCurrency, formatDateTime, formatNumber, formatSqft, parkingSourceLabel } from "@/lib/format";
import type { AnalyzeResponse } from "@/lib/types";
import { Badge } from "../ui/Badge";

function Chip({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface px-3 py-2">
      <p className="text-xs text-ink-muted">{label}</p>
      <p className="text-sm font-medium">{value}</p>
    </div>
  );
}

function sqftRange(min: number | null, max: number | null): string {
  if (min === null && max === null) return "N/A";
  if (min !== null && max !== null) return `${formatNumber(min)}–${formatSqft(max)}`;
  return min !== null ? `≥ ${formatSqft(min)}` : `≤ ${formatSqft(max)}`;
}

/** Report header: parsed requirements, assumptions, ranking basis and provider modes. */
export function RequirementsSummary({ analysis }: { analysis: AnalyzeResponse }) {
  const req = analysis.requirements;
  const modes = Object.entries(analysis.mode ?? {});

  return (
    <section className="grid gap-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium uppercase tracking-widest text-accent">Analysis report</p>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            {req.business_label || analysis.business_type} in {req.city}
            {req.state ? `, ${req.state}` : ""}
          </h1>
          <p className="text-sm text-ink-muted">
            {analysis.results.length} {analysis.results.length === 1 ? "space" : "spaces"} compared ·{" "}
            {formatDateTime(analysis.created_at)}
          </p>
        </div>
        {modes.length > 0 && (
          <div className="flex flex-wrap gap-1.5" aria-label="Data sources">
            {modes.map(([provider, mode]) => (
              <Badge key={provider} tone={mode === "live" || mode === "claude" ? "accent" : "neutral"}>
                {provider}: {mode}
              </Badge>
            ))}
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        <Chip label="Capacity" value={formatNumber(req.capacity, req.capacity_unit)} />
        <Chip label="Occupant load" value={formatNumber(req.occupant_load, "people")} />
        <Chip
          label={`Parking (${parkingSourceLabel(req.parking_source)})`}
          value={formatNumber(req.parking_required, "spaces")}
        />
        <Chip label="Bathrooms" value={formatNumber(req.bathrooms_required)} />
        <Chip label="Kitchen" value={req.needs_kitchen ? "Required" : "Not needed"} />
        <Chip label="HVAC / electrical" value={`${formatNumber(req.required_hvac_tons)} tons · ${formatNumber(req.required_electrical_amps)} A`} />
        <Chip label="Size" value={sqftRange(req.min_sqft, req.max_sqft)} />
        <Chip label="Max rent" value={req.max_rent !== null ? `${formatCurrency(req.max_rent)}/mo` : "N/A"} />
      </div>

      <div className="grid gap-3 rounded-xl border border-line bg-surface p-4 text-sm">
        <p>
          <span className="font-medium">How we ranked: </span>
          <span className="text-ink-muted">{analysis.ranking_basis || "N/A"}</span>
        </p>
        {req.assumptions?.length > 0 && (
          <div>
            <p className="font-medium">Assumptions</p>
            <ul className="mt-1 list-inside list-disc space-y-0.5 text-ink-muted">
              {req.assumptions.map((assumption, index) => (
                <li key={index}>{assumption}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}
