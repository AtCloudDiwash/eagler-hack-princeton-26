"use client";

import { CheckIcon } from "@heroicons/react/20/solid";
import { hasLlm, isLocalLlm } from "@/lib/format";
import { Spinner } from "./ui/Spinner";

export const ANALYSIS_STEPS: readonly string[] = [
  "Parsing requirements",
  "Reading listings",
  "Checking compliance",
  "Estimating fit-out",
];

/**
 * Progress steps for a run. When the backend has a summary LLM (`/health` mode.llm), a final
 * "Writing summary" step makes its extra few seconds read as intentional work.
 */
export function analysisSteps(llm: string | null | undefined): readonly string[] {
  if (!hasLlm(llm)) return ANALYSIS_STEPS;
  return [...ANALYSIS_STEPS, isLocalLlm(llm) ? "Writing summary (local AI)" : "Writing summary (AI)"];
}

/** Full-screen overlay shown while POST /api/v1/analyze runs. `step` advances on a timer in the parent. */
export function AnalyzeProgress({
  step,
  count,
  steps = ANALYSIS_STEPS,
}: {
  step: number;
  count: number;
  steps?: readonly string[];
}) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-navy-950/80 px-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-labelledby="analyze-title">
      <div className="w-full max-w-sm rounded-xl border border-line bg-surface p-6 shadow-2xl">
        <div className="mb-4 flex items-center gap-3">
          <Spinner className="size-6" label="Analyzing" />
          <h2 id="analyze-title" className="font-semibold">
            Analyzing {count} {count === 1 ? "space" : "spaces"}…
          </h2>
        </div>
        <ol className="grid gap-2.5 text-sm">
          {steps.map((label, index) => {
            const done = index < step;
            const active = index === step;
            return (
              <li key={label} className={`flex items-center gap-2.5 ${done || active ? "text-ink" : "text-ink-muted"}`}>
                <span
                  className={`grid size-5 place-items-center rounded-full border text-[10px] ${
                    done ? "border-accent bg-accent text-navy-950" : active ? "border-accent text-accent" : "border-line"
                  }`}
                >
                  {done ? <CheckIcon className="size-3.5" aria-hidden /> : index + 1}
                </span>
                {label}
                {active && "…"}
              </li>
            );
          })}
        </ol>
      </div>
    </div>
  );
}
