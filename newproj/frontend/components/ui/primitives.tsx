"use client";

import { type ReactNode, useState } from "react";

export function Pill({ children, className = "", title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ring-inset ${className}`}>
      {children}
    </span>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-2xl border border-line bg-ink-900/80 shadow-[0_1px_0_rgba(255,255,255,0.03)_inset] ${className}`}>{children}</div>;
}

export function SectionTitle({ eyebrow, title, right, id }: { eyebrow?: string; title: string; right?: ReactNode; id?: string }) {
  return (
    <div id={id} className="mb-3 flex scroll-mt-20 flex-wrap items-end justify-between gap-2">
      <div>
        {eyebrow && <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-400/80">{eyebrow}</div>}
        <h2 className="text-lg font-semibold text-slate-100">{title}</h2>
      </div>
      {right}
    </div>
  );
}

/** Circular score gauge (0-100). */
export function ScoreRing({ value, size = 132, color = "#2dd4bf", label = "score" }: { value: number; size?: number; color?: string; label?: string }) {
  const stroke = size * 0.085;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, value));
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0" role="img" aria-label={`${label} ${Math.round(v)} of 100`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1f2d4d" strokeWidth={stroke} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={`${(c * v) / 100} ${c}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: "stroke-dasharray 900ms ease" }}
      />
      <text x="50%" y="48%" textAnchor="middle" dominantBaseline="middle" fill="#f1f5f9" fontSize={size * 0.27} fontWeight={700}>
        {Math.round(v)}
      </text>
      <text x="50%" y="68%" textAnchor="middle" fill="#64748b" fontSize={size * 0.09} letterSpacing="0.12em">
        {label.toUpperCase()}
      </text>
    </svg>
  );
}

/** Horizontal 0-100 meter. */
export function Meter({ value, color = "#2dd4bf", className = "h-1.5" }: { value: number | null; color?: string; className?: string }) {
  return (
    <div className={`w-full overflow-hidden rounded-full bg-ink-700/60 ${className}`}>
      {value != null && <div className="h-full rounded-full" style={{ width: `${Math.max(2, Math.min(100, value))}%`, background: color, transition: "width 700ms ease" }} />}
    </div>
  );
}

/** A low–high range drawn on a shared scale (0..max). */
export function RangeBar({ low, high, max, color = "#2dd4bf" }: { low: number; high: number; max: number; color?: string }) {
  const l = max > 0 ? (low / max) * 100 : 0;
  const h = max > 0 ? (high / max) * 100 : 0;
  return (
    <div className="relative h-2 w-full rounded-full bg-ink-700/50">
      <div className="absolute inset-y-0 rounded-full" style={{ left: `${l}%`, width: `${Math.max(1.5, h - l)}%`, background: color, opacity: 0.85 }} />
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin text-teal-400 ${className}`} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
      <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function Collapsible({ title, children, defaultOpen = false, count }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean; count?: number }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-line/70">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between gap-2 py-2.5 text-left text-xs font-medium text-slate-300 hover:text-teal-300">
        <span className="flex items-center gap-2">
          <span className={`inline-block transition-transform ${open ? "rotate-90" : ""}`}>›</span>
          {title}
        </span>
        {count != null && <span className="rounded-full bg-ink-700/70 px-2 text-[10px] text-slate-400">{count}</span>}
      </button>
      {open && <div className="pb-3">{children}</div>}
    </div>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-line px-3 py-3 text-xs text-slate-500">{children}</p>;
}
