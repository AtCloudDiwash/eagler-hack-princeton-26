import { InformationCircleIcon } from "@heroicons/react/16/solid";
import type { ReactNode } from "react";

/**
 * Small "i" icon with a hover/focus tooltip (pure CSS, keyboard accessible).
 * Used for source citations on compliance rows.
 */
export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex align-middle">
      <button
        type="button"
        aria-label={label}
        className="rounded-full text-ink-muted hover:text-accent focus-visible:text-accent focus-visible:outline-none"
      >
        <InformationCircleIcon className="size-4" aria-hidden />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none invisible absolute bottom-full right-0 z-30 mb-2 w-64 max-w-[80vw] rounded-lg border border-line bg-navy-900 p-2.5 text-xs font-normal normal-case leading-relaxed tracking-normal text-ink opacity-0 shadow-xl transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100 sm:left-1/2 sm:right-auto sm:-translate-x-1/2"
      >
        {children}
      </span>
    </span>
  );
}
