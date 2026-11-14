export function Spinner({ className = "size-5", label = "Loading" }: { className?: string; label?: string }) {
  return (
    <span role="status" aria-label={label} className="inline-flex">
      <svg className={`animate-spin text-accent ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
        <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>
    </span>
  );
}

/** Centered spinner with a caption, used as page-level loading and Suspense fallback. */
export function LoadingBlock({ message = "Loading…" }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-sm text-ink-muted">
      <Spinner className="size-7" label={message} />
      <p>{message}</p>
    </div>
  );
}
