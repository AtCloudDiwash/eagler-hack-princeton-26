import { CheckCircleIcon, ExclamationTriangleIcon, QuestionMarkCircleIcon } from "@heroicons/react/20/solid";
import type { ReactNode } from "react";
import type { Status } from "@/lib/types";

type Tone = "neutral" | "accent" | "pass" | "risk" | "unknown" | "danger";

const tones: Record<Tone, string> = {
  neutral: "border-line bg-surface-raised text-ink-muted",
  accent: "border-accent/40 bg-accent/10 text-accent",
  pass: "border-pass/40 bg-pass/10 text-pass",
  risk: "border-risk/40 bg-risk/10 text-risk",
  unknown: "border-unknown/40 bg-unknown/10 text-unknown",
  danger: "border-red-400/40 bg-red-400/10 text-red-300",
};

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

const statusConfig: Record<Status, { tone: Tone; label: string; Icon: typeof CheckCircleIcon }> = {
  PASS: { tone: "pass", label: "PASS", Icon: CheckCircleIcon },
  RISK: { tone: "risk", label: "RISK", Icon: ExclamationTriangleIcon },
  UNKNOWN: { tone: "unknown", label: "UNKNOWN", Icon: QuestionMarkCircleIcon },
};

/** PASS (green) / RISK (orange) / UNKNOWN (gray). Unexpected values fall back to UNKNOWN. */
export function StatusBadge({ status }: { status: Status | string }) {
  const config = statusConfig[status as Status] ?? statusConfig.UNKNOWN;
  const { Icon } = config;
  return (
    <span data-status={config.label}>
      <Badge tone={config.tone}>
        <Icon className="size-3.5" aria-hidden />
        {config.label}
      </Badge>
    </span>
  );
}
