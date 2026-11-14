"use client";

import { CheckIcon } from "@heroicons/react/20/solid";
import { Spinner } from "./ui/Spinner";

export const ANALYSIS_STEPS = [
  "Parsing requirements",
  "Reading listings",
  "Checking compliance",
  "Estimating fit-out",
] as const;

/** Full-screen overlay shown while POST /api/v1/analyze runs. `step` advances on a timer in the parent. */
export function AnalyzeProgress({ step, count }: { step: number; count: number }) {
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
          {ANALYSIS_STEPS.map((label, index) => {
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
