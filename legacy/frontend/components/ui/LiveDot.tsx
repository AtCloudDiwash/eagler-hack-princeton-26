/** Tiny "live" marker for evidence that came from a live provider call (not fixtures or derived). */
export function LiveDot({ live }: { live: boolean | undefined }) {
  if (!live) return null;
  return (
    <span
      data-testid="live-evidence"
      title="From a live provider call"
      className="inline-flex shrink-0 items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-accent"
    >
      <span className="size-1.5 rounded-full bg-accent" aria-hidden />
      live
    </span>
  );
}
