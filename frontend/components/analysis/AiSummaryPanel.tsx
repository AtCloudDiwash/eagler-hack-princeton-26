import { SparklesIcon } from "@heroicons/react/20/solid";
import { llmLabel } from "@/lib/format";
import type { AiSummary } from "@/lib/types";
import { Badge } from "../ui/Badge";

export const AI_SUMMARY_CAVEAT = "Written by AI from the numbers below; costs and compliance are rule-based.";

/**
 * Plain-English explanation of the ranking from the backend's LLM. Renders nothing when the run
 * has no summary (no LLM reachable, call failed, or an older stored run), so there's never an empty panel.
 */
export function AiSummaryPanel({ summary }: { summary: AiSummary | null | undefined }) {
  const text = summary?.text?.trim();
  if (!summary || !text) return null;

  return (
    <section
      aria-labelledby="ai-summary-title"
      className="grid gap-2 rounded-xl border border-accent/30 bg-accent/5 p-4 sm:p-5"
      data-testid="ai-summary"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="ai-summary-title" className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-accent">
          <SparklesIcon className="size-4" aria-hidden /> AI summary
        </h2>
        <Badge tone="accent" title={summary.model}>
          {llmLabel(summary.model)}
        </Badge>
      </div>
      <p className="text-sm leading-relaxed sm:text-base">{text}</p>
      <p className="text-xs text-ink-muted">{AI_SUMMARY_CAVEAT}</p>
    </section>
  );
}

/** One-sentence "why this rank" for a property, or null when the summary doesn't cover it. */
export function aiSentenceFor(summary: AiSummary | null | undefined, propertyId: string): string | null {
  const sentence = summary?.per_property?.[propertyId]?.trim();
  return sentence ? sentence : null;
}
