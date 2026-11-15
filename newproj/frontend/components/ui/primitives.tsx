"use client";

import { AnimatePresence, animate, motion, useMotionValue, useTransform } from "motion/react";
import { ChevronRight } from "lucide-react";
import { type ReactNode, useEffect, useId, useState } from "react";

export function Pill({ children, className = "", title }: { children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ring-inset ${className}`}>
      {children}
    </span>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`glass rounded-2xl ${className}`}>{children}</div>;
}

export function SectionTitle({ eyebrow, title, right, id }: { eyebrow?: string; title: string; right?: ReactNode; id?: string }) {
  return (
    <div id={id} className="mb-3 flex scroll-mt-24 flex-wrap items-end justify-between gap-2">
      <div>
        {eyebrow && <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-teal-400/80">{eyebrow}</div>}
        <h2 className="text-base font-semibold text-slate-100">{title}</h2>
      </div>
      {right}
    </div>
  );
}

/** Number that counts up to its value. */
export function AnimatedNumber({ value, duration = 1.2, format = (n: number) => String(Math.round(n)) }: { value: number; duration?: number; format?: (n: number) => string }) {
  const mv = useMotionValue(0);
  const text = useTransform(mv, (v) => format(v));
  useEffect(() => {
    const c = animate(mv, value, { duration, ease: [0.16, 1, 0.3, 1] });
    return () => c.stop();
  }, [value, duration, mv]);
  return <motion.span>{text}</motion.span>;
}

/** Circular score gauge (0-100) that draws itself and counts up. */
export function ScoreRing({ value, size = 132, color = "#d4f53a", label = "score", animateIn = true }: { value: number; size?: number; color?: string; label?: string; animateIn?: boolean }) {
  const stroke = Math.max(4, size * 0.08);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, value));
  const gid = useId().replace(/:/g, "");
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={`${label} ${Math.round(v)} of 100`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <defs>
          <linearGradient id={`g${gid}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={color} />
            <stop offset="100%" stopColor="#e2fb5c" />
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="rgba(148,163,184,0.14)" strokeWidth={stroke} />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={`url(#g${gid})`}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: animateIn ? c : c - (c * v) / 100 }}
          animate={{ strokeDashoffset: c - (c * v) / 100 }}
          transition={{ duration: 1.3, ease: [0.16, 1, 0.3, 1] }}
          style={{ filter: size >= 80 ? `drop-shadow(0 0 ${size / 18}px ${color}66)` : undefined }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center leading-none">
        <div>
          <div className="font-display font-semibold tabular-nums text-slate-50" style={{ fontSize: size * 0.3 }}>
            {animateIn ? <AnimatedNumber value={v} /> : Math.round(v)}
          </div>
          {size >= 64 && (
            <div className="mt-1 uppercase tracking-[0.16em] text-slate-500" style={{ fontSize: Math.max(8, size * 0.075) }}>
              {label}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Horizontal 0-100 meter. */
export function Meter({ value, color = "#d4f53a", className = "h-1.5" }: { value: number | null; color?: string; className?: string }) {
  return (
    <div className={`w-full overflow-hidden rounded-full bg-white/[0.06] ${className}`}>
      {value != null && (
        <motion.div className="h-full rounded-full" style={{ background: color }} initial={{ width: 0 }} animate={{ width: `${Math.max(2, Math.min(100, value))}%` }} transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }} />
      )}
    </div>
  );
}

/** A low–high range drawn on a shared scale (0..max). */
export function RangeBar({ low, high, max, color = "#d4f53a" }: { low: number; high: number; max: number; color?: string }) {
  const l = max > 0 ? (low / max) * 100 : 0;
  const h = max > 0 ? (high / max) * 100 : 0;
  return (
    <div className="relative h-2 w-full rounded-full bg-white/[0.06]">
      <motion.div
        className="absolute inset-y-0 rounded-full"
        style={{ left: `${l}%`, background: `linear-gradient(90deg, ${color}99, ${color})` }}
        initial={{ width: 0 }}
        whileInView={{ width: `${Math.max(1.5, h - l)}%` }}
        viewport={{ once: true }}
        transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
      />
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

/** Animated disclosure. */
export function Collapsible({ title, children, defaultOpen = false, count, className = "" }: { title: ReactNode; children: ReactNode; defaultOpen?: boolean; count?: number; className?: string }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={className}>
      <button onClick={() => setOpen((o) => !o)} className="group flex w-full items-center justify-between gap-2 py-2.5 text-left text-xs font-medium text-slate-300 hover:text-teal-200" aria-expanded={open}>
        <span className="flex items-center gap-2">
          <motion.span animate={{ rotate: open ? 90 : 0 }} transition={{ duration: 0.2 }} className="text-slate-500 group-hover:text-teal-300">
            <ChevronRight size={14} />
          </motion.span>
          {title}
        </span>
        {count != null && <span className="rounded-full bg-white/[0.06] px-2 text-[10px] text-slate-400">{count}</span>}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }} className="overflow-hidden">
            <div className="pb-3">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Segmented tabs with a sliding indicator. */
export function Tabs<T extends string>({ tabs, value, onChange, layoutId, className = "" }: { tabs: { id: T; label: ReactNode; icon?: ReactNode }[]; value: T; onChange: (v: T) => void; layoutId: string; className?: string }) {
  return (
    <div role="tablist" className={`flex gap-1 overflow-x-auto rounded-2xl bg-white/[0.03] p-1 ring-1 ring-inset ring-white/[0.06] ${className}`}>
      {tabs.map((t) => {
        const on = t.id === value;
        return (
          <button key={t.id} role="tab" aria-selected={on} onClick={() => onChange(t.id)} className={`relative shrink-0 rounded-xl px-3.5 py-2 text-xs font-medium transition-colors ${on ? "text-ink-950" : "text-slate-400 hover:text-slate-100"}`}>
            {on && <motion.span layoutId={layoutId} className="absolute inset-0 rounded-xl bg-gradient-to-r from-teal-300 to-cyan-300" transition={{ type: "spring", stiffness: 420, damping: 34 }} />}
            <span className="relative flex items-center gap-1.5">
              {t.icon}
              {t.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function StatTile({ icon, label, value, sub, hint, accent = "#d4f53a", muted = false }: { icon?: ReactNode; label: string; value: ReactNode; sub?: ReactNode; hint?: string; accent?: string; muted?: boolean }) {
  return (
    <div className="rounded-xl bg-white/[0.035] p-2.5 ring-1 ring-inset ring-white/[0.06]" title={hint}>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-slate-500">
        {icon && <span style={{ color: accent }}>{icon}</span>}
        {label}
      </div>
      <div className={`mt-1 truncate text-sm ${muted ? "font-normal text-slate-500" : "font-semibold text-slate-100"}`}>{value}</div>
      {sub && <div className="mt-0.5 line-clamp-2 text-[10.5px] leading-snug text-slate-500">{sub}</div>}
    </div>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="rounded-xl border border-dashed border-white/10 px-3 py-3 text-xs text-slate-500">{children}</p>;
}

/** Staggered list container + item for entrance animations. */
export const stagger = {
  container: { hidden: {}, show: { transition: { staggerChildren: 0.045 } } },
  item: { hidden: { opacity: 0, y: 10 }, show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.16, 1, 0.3, 1] as const } } },
};
