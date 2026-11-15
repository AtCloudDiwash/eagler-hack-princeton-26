import type { ComponentProps, ReactNode } from "react";

export function Card({ className = "", ...props }: ComponentProps<"div">) {
  return <div className={`rounded-xl border border-line bg-surface shadow-lg shadow-black/20 ${className}`} {...props} />;
}

/** Section heading used inside cards and pages. */
export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h3 className="text-sm font-semibold uppercase tracking-wider text-ink-muted">{children}</h3>
      {action}
    </div>
  );
}
