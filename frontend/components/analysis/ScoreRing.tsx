/** Circular 0-100 criteria-fit score. Disqualified properties are drawn in the risk color. */
export function ScoreRing({ score, disqualified = false, size = 64 }: { score: number; disqualified?: boolean; size?: number }) {
  const value = Math.max(0, Math.min(100, Number.isFinite(score) ? score : 0));
  const radius = 15.9155; // circumference = 100, so dash lengths map straight to percentages
  const color = disqualified ? "text-risk" : value >= 75 ? "text-pass" : value >= 50 ? "text-accent" : "text-risk";
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`Fit score ${Math.round(value)} out of 100`}>
      <svg viewBox="0 0 36 36" className="size-full -rotate-90" aria-hidden>
        <circle cx="18" cy="18" r={radius} fill="none" stroke="currentColor" strokeWidth="3" className="text-line" />
        <circle
          cx="18"
          cy="18"
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={`${value} ${100 - value}`}
          className={color}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center text-sm font-semibold tabular-nums">{Math.round(value)}</span>
    </div>
  );
}
