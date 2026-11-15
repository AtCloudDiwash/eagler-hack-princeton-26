import { ExclamationTriangleIcon } from "@heroicons/react/16/solid";
import { Badge } from "../ui/Badge";
import { InfoTip } from "../ui/InfoTip";

/** Explains the backend's min-score gate (costs.yaml ranking.min_score). */
export function weakFitExplanation(minScore?: number) {
  const threshold = minScore !== undefined ? String(minScore) : "the minimum";
  return `Fit score below ${threshold} — ranked after better-fitting spaces`;
}

/** Orange "Weak fit" badge + InfoTip, rendered only for results with `weak_fit: true`. */
export function WeakFitBadge({ weakFit, minScore }: { weakFit?: boolean; minScore?: number }) {
  if (!weakFit) return null;
  return (
    <span className="inline-flex items-center gap-1" data-testid="weak-fit">
      <Badge tone="risk">
        <ExclamationTriangleIcon className="size-3" aria-hidden /> Weak fit
      </Badge>
      <InfoTip label="Why weak fit?">{weakFitExplanation(minScore)}</InfoTip>
    </span>
  );
}
