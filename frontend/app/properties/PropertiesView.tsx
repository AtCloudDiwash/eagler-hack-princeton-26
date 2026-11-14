"use client";

import { ArrowLeftIcon, ArrowRightIcon, ChevronDownIcon } from "@heroicons/react/20/solid";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ANALYSIS_STEPS, AnalyzeProgress } from "@/components/AnalyzeProgress";
import { CriteriaTable } from "@/components/CriteriaTable";
import { PropertyCard } from "@/components/PropertyCard";
import { Button, ButtonLink } from "@/components/ui/Button";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { LoadingBlock, Spinner } from "@/components/ui/Spinner";
import { api, errorMessage } from "@/lib/api";
import { humanize } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

const STEP_INTERVAL_MS = 1400;

export function PropertiesView() {
  const router = useRouter();
  const params = useSearchParams();
  const type = params.get("type")?.trim() ?? "";
  const details = params.get("details")?.trim() ?? "";
  const city = params.get("city")?.trim() ?? "";
  const state = params.get("state")?.trim() ?? "";
  const query = { business_type: type, city, state };
  const queryKey = JSON.stringify(query);

  const properties = useAsync((signal) => api.properties(query, { signal }), `properties:${queryKey}`);
  const criteria = useAsync((signal) => api.criteria(query, { signal }), `criteria:${queryKey}`);

  const [selected, setSelected] = useState<string[]>([]);
  const [analyzing, setAnalyzing] = useState(false);
  const [step, setStep] = useState(0);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);

  // Advance the cosmetic progress steps while the analysis request is in flight.
  useEffect(() => {
    if (!analyzing) return;
    const timer = setInterval(() => setStep((s) => Math.min(s + 1, ANALYSIS_STEPS.length - 1)), STEP_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [analyzing]);

  if (!type) {
    return (
      <EmptyState
        title="Start with a business profile"
        message="Tell us what kind of business you're opening and where, and we'll find candidate spaces."
        action={<ButtonLink href="/" variant="primary">Create profile</ButtonLink>}
      />
    );
  }

  const listings = properties.status === "success" ? properties.data : [];
  // Ignore stale selections that aren't in the current result set.
  const selectedIds = selected.filter((id) => listings.some((p) => p.id === id));

  function toggle(id: string) {
    setSelected((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]));
  }

  async function compare() {
    if (selectedIds.length === 0 || analyzing) return;
    setAnalyzeError(null);
    setStep(0);
    setAnalyzing(true);
    try {
      const result = await api.analyze({
        business_profile: { type, details, city, state },
        property_ids: selectedIds,
      });
      router.push(`/analysis/${result.analysis_id}`);
    } catch (error) {
      setAnalyzeError(errorMessage(error));
      setAnalyzing(false);
    }
  }

  const where = [city, state].filter(Boolean).join(", ") || "any location";

  return (
    <div className="grid gap-6 pb-24">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="grid gap-1">
          <ButtonLink href="/" variant="ghost" size="sm" className="-ml-3 justify-self-start">
            <ArrowLeftIcon className="size-4" aria-hidden /> Edit profile
          </ButtonLink>
          <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Spaces for a {humanize(type).toLowerCase()} in {where}
          </h1>
          <p className="text-sm text-ink-muted">
            {details ? <>Requirements: &ldquo;{details}&rdquo;</> : "No extra requirements given; local guidelines will be assumed."}
          </p>
        </div>
        {listings.length > 0 && (
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => setSelected(listings.map((p) => p.id))}>
              Select all
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setSelected([])} disabled={selectedIds.length === 0}>
              Clear
            </Button>
          </div>
        )}
      </div>

      {analyzeError && (
        <ErrorState title="Analysis failed" message={analyzeError} onRetry={compare} />
      )}

      {properties.status === "loading" && <LoadingBlock message="Reading listings…" />}
      {properties.status === "error" && (
        <ErrorState title="Couldn't load spaces" message={errorMessage(properties.error)} onRetry={properties.retry} />
      )}
      {properties.status === "success" && listings.length === 0 && (
        <EmptyState
          title="No spaces found"
          message={`No available listings matched ${where}. Try a different city or ZIP.`}
          action={<ButtonLink href="/">Change location</ButtonLink>}
        />
      )}
      {listings.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {listings.map((property) => (
            <PropertyCard
              key={property.id}
              property={property}
              selected={selectedIds.includes(property.id)}
              onToggle={toggle}
            />
          ))}
        </div>
      )}

      <details className="group rounded-xl border border-line bg-surface">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm font-medium [&::-webkit-details-marker]:hidden">
          <span>
            Criteria used
            {criteria.status === "success" && <span className="text-ink-muted"> ({criteria.data.length})</span>}
          </span>
          <ChevronDownIcon className="size-5 text-ink-muted transition-transform group-open:rotate-180" aria-hidden />
        </summary>
        <div className="border-t border-line p-4">
          <p className="mb-3 text-xs text-ink-muted">
            Loaded from the criteria registry for this business type and jurisdiction. Hard-block criteria disqualify a
            space when they fail.
          </p>
          {criteria.status === "loading" && <Spinner label="Loading criteria" />}
          {criteria.status === "error" && (
            <div className="flex flex-wrap items-center gap-3 text-sm text-ink-muted">
              <span>Couldn&apos;t load criteria: {errorMessage(criteria.error)}</span>
              <Button variant="secondary" size="sm" onClick={criteria.retry}>Try again</Button>
            </div>
          )}
          {criteria.status === "success" && <CriteriaTable criteria={criteria.data} />}
        </div>
      </details>

      {selectedIds.length > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-navy-900/95 backdrop-blur">
          <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-3 px-4 py-3">
            <p className="text-sm text-ink-muted">
              <span className="font-semibold text-ink">{selectedIds.length}</span> of {listings.length} selected
            </p>
            <Button onClick={compare} disabled={analyzing}>
              Compare {selectedIds.length} selected <ArrowRightIcon className="size-4" aria-hidden />
            </Button>
          </div>
        </div>
      )}

      {analyzing && <AnalyzeProgress step={step} count={selectedIds.length} />}
    </div>
  );
}
