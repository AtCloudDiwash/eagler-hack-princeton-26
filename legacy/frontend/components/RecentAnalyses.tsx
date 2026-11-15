"use client";

import { ChevronRightIcon } from "@heroicons/react/20/solid";
import Link from "next/link";
import { api } from "@/lib/api";
import { formatDateTime, orNA } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";

/** Stored runs from GET /api/v1/analyses. Renders nothing when empty or when the API is down. */
export function RecentAnalyses() {
  const recent = useAsync((signal) => api.analyses(10, { signal }), "recent-analyses");
  if (recent.status !== "success" || recent.data.length === 0) return null;

  return (
    <section id="recent" className="scroll-mt-20">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-ink-muted">Recent analyses</h2>
      <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
        {recent.data.map((run) => (
          <li key={run.analysis_id}>
            <Link
              href={`/analysis/${run.analysis_id}`}
              className="flex items-center gap-3 px-4 py-3 text-sm transition-colors hover:bg-surface-raised"
            >
              <div className="min-w-0 flex-1">
                <p className="font-medium">
                  {orNA(run.business_label)} · {run.city}
                  {run.state ? `, ${run.state}` : ""}
                </p>
                <p className="truncate text-xs text-ink-muted">
                  {run.property_count} {run.property_count === 1 ? "space" : "spaces"} compared · Top pick:{" "}
                  {orNA(run.top_address)} · {formatDateTime(run.created_at)}
                </p>
              </div>
              <ChevronRightIcon className="size-5 shrink-0 text-ink-muted" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
