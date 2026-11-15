import { ExclamationCircleIcon, InboxIcon } from "@heroicons/react/24/outline";
import type { ReactNode } from "react";
import { Button } from "./Button";

interface EmptyStateProps {
  title: string;
  message?: ReactNode;
  action?: ReactNode;
  tone?: "empty" | "error";
}

export function EmptyState({ title, message, action, tone = "empty" }: EmptyStateProps) {
  const Icon = tone === "error" ? ExclamationCircleIcon : InboxIcon;
  return (
    <div
      role={tone === "error" ? "alert" : undefined}
      className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-line bg-surface/60 px-6 py-12 text-center"
    >
      <Icon className={`size-9 ${tone === "error" ? "text-risk" : "text-ink-muted"}`} aria-hidden />
      <h2 className="text-base font-semibold">{title}</h2>
      {message && <div className="max-w-md text-sm text-ink-muted">{message}</div>}
      {action}
    </div>
  );
}

/** Error variant with an optional "Try again" button. */
export function ErrorState({ title = "Something went wrong", message, onRetry, extra }: {
  title?: string;
  message: ReactNode;
  onRetry?: () => void;
  extra?: ReactNode;
}) {
  return (
    <EmptyState
      tone="error"
      title={title}
      message={message}
      action={
        (onRetry || extra) && (
          <div className="flex flex-wrap justify-center gap-2">
            {onRetry && (
              <Button variant="secondary" onClick={onRetry}>
                Try again
              </Button>
            )}
            {extra}
          </div>
        )
      }
    />
  );
}
