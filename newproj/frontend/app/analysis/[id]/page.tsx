"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Analysis } from "@/lib/api-types";
import AnalysisView from "@/components/analysis/AnalysisView";
import { Spinner } from "@/components/ui/primitives";

const POLL_MS = 1500;

export default function AnalysisPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    const ctrl = new AbortController();

    const poll = async () => {
      try {
        const a = await api.analysis(id, ctrl.signal);
        if (cancelled) return;
        failures = 0;
        setError(null);
        setAnalysis(a);
        if (a.status === "queued" || a.status === "running") timer = setTimeout(poll, POLL_MS);
      } catch (e) {
        if (cancelled || (e as Error).name === "AbortError") return;
        failures += 1;
        setError((e as Error).message);
        // Keep retrying transient failures (backend restart), back off a little.
        if (failures < 20) timer = setTimeout(poll, POLL_MS * Math.min(4, failures));
      }
    };
    poll();
    return () => {
      cancelled = true;
      ctrl.abort();
      if (timer) clearTimeout(timer);
    };
  }, [id]);

  if (!analysis) {
    return (
      <div className="grid min-h-dvh place-items-center bg-ink-950 p-6 text-center">
        {error ? (
          <div className="max-w-md space-y-3">
            <p className="text-sm text-rose-300">{error}</p>
            <Link href="/" className="text-xs text-teal-300 hover:underline">
              ← Back to the map
            </Link>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <Spinner /> Loading analysis…
          </div>
        )}
      </div>
    );
  }
  return <AnalysisView analysis={analysis} />;
}
