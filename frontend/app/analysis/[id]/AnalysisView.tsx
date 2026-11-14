"use client";

import { ArrowLeftIcon } from "@heroicons/react/20/solid";
import { useParams } from "next/navigation";
import { AnalysisCard } from "@/components/analysis/AnalysisCard";
import { ComparisonTable } from "@/components/analysis/ComparisonTable";
import { RequirementsSummary } from "@/components/analysis/RequirementsSummary";
import { ButtonLink } from "@/components/ui/Button";
import { EmptyState, ErrorState } from "@/components/ui/EmptyState";
import { LoadingBlock } from "@/components/ui/Spinner";
import { ApiError, api, errorMessage, toQuery } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";

export function AnalysisView() {
  const { id } = useParams<{ id: string }>();
  const analysis = useAsync((signal) => api.analysis(id, { signal }), `analysis:${id}`);

  if (analysis.status === "loading") return <LoadingBlock message="Loading analysis…" />;

  if (analysis.status === "error") {
    if (analysis.error instanceof ApiError && analysis.error.status === 404) {
      return (
        <EmptyState
          title="Analysis not found"
          message={`No stored analysis has the id "${id}". It may have been created on another machine.`}
          action={<ButtonLink href="/" variant="primary">Start a new search</ButtonLink>}
        />
      );
    }
    return (
      <ErrorState
        title="Couldn't load this analysis"
        message={errorMessage(analysis.error)}
        onRetry={analysis.retry}
        extra={<ButtonLink href="/">Back home</ButtonLink>}
      />
    );
  }

  const data = analysis.data;
  const req = data.requirements;
  const backHref = `/properties${toQuery({ type: data.business_type, city: req.city, state: req.state })}`;
  const results = [...data.results].sort((a, b) => a.rank - b.rank);

  return (
    <div className="grid gap-8">
      <ButtonLink href={backHref} variant="ghost" size="sm" className="-ml-3 justify-self-start">
        <ArrowLeftIcon className="size-4" aria-hidden /> Back to spaces
      </ButtonLink>

      <RequirementsSummary analysis={data} />

      {results.length === 0 ? (
        <EmptyState title="No results" message="This analysis has no property results." />
      ) : (
        <>
          <section className="grid gap-3">
            <h2 className="text-lg font-semibold">Side-by-side</h2>
            <ComparisonTable results={results} />
          </section>
          <section className="grid gap-6">
            {results.map((result) => (
              <AnalysisCard key={result.property_id} result={result} />
            ))}
          </section>
        </>
      )}

      <p className="rounded-lg border border-line bg-surface/60 p-4 text-xs leading-relaxed text-ink-muted">
        <span className="font-semibold text-ink">Disclaimer: </span>
        {data.disclaimer ||
          "Estimates are planning ranges from a rule-based model, not contractor quotes. Verify compliance with your local jurisdiction."}
      </p>
    </div>
  );
}
