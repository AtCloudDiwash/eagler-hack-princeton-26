import { InformationCircleIcon } from "@heroicons/react/16/solid";
import type { ReactNode } from "react";

/**
 * Small "i" icon with a hover/focus tooltip (pure CSS, keyboard accessible).
 * Used for source citations on compliance rows and listing notes.
 *
 * Uses a named group (`group/tip`) so hovering an ancestor that is itself a `.group` (e.g. a whole
 * PropertyCard) doesn't open the tooltip. `align="start"` anchors the tooltip's left edge to the icon,
 * for icons near the left edge of a clipped container; the default flips right/center by breakpoint.
 */
export function InfoTip({
  label,
  children,
  align = "auto",
}: {
  label: string;
  children: ReactNode;
  align?: "auto" | "start";
}) {
  const position = align === "start" ? "left-0" : "right-0 sm:left-1/2 sm:right-auto sm:-translate-x-1/2";
  return (
    <span className="group/tip relative inline-flex align-middle">
      <button
        type="button"
        aria-label={label}
        className="rounded-full text-ink-muted hover:text-accent focus-visible:text-accent focus-visible:outline-none"
      >
        <InformationCircleIcon className="size-4" aria-hidden />
      </button>
      <span
        role="tooltip"
        className={`pointer-events-none invisible absolute bottom-full z-30 mb-2 w-64 max-w-[80vw] whitespace-normal rounded-lg border border-line bg-navy-900 p-2.5 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-ink opacity-0 shadow-xl transition-opacity group-focus-within/tip:visible group-focus-within/tip:opacity-100 group-hover/tip:visible group-hover/tip:opacity-100 ${position}`}
      >
        {children}
      </span>
    </span>
  );
}
