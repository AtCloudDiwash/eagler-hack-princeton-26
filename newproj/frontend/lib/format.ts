/** Formatting + color helpers shared by discovery and dashboard. */
import type { AgentName, MetricStatus, Verdict } from "./api-types";

export const fmtMoney = (n: number | null | undefined, compact = true) => {
  if (n == null || !Number.isFinite(n)) return "—";
  if (compact && Math.abs(n) >= 1000) {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 }).format(n);
  }
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
};

export const fmtRange = (low: number | null | undefined, high: number | null | undefined) =>
  low == null || high == null ? "—" : low === high ? fmtMoney(low) : `${fmtMoney(low)} – ${fmtMoney(high)}`;

export const fmtNum = (n: number | null | undefined, digits = 0) =>
  n == null || !Number.isFinite(n) ? "—" : n.toLocaleString("en-US", { maximumFractionDigits: digits });

export const fmtSqft = (n: number | null | undefined) => (n == null ? "—" : `${fmtNum(n)} sq ft`);

export const fmtDistance = (m: number | null | undefined) =>
  m == null ? "—" : m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;

export const titleCase = (s: string | null | undefined) =>
  (s ?? "").replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const VERDICT_STYLE: Record<Verdict, { label: string; text: string; bg: string; ring: string; color: string }> = {
  recommended: { label: "Recommended", text: "text-emerald-300", bg: "bg-emerald-500/15", ring: "ring-emerald-400/40", color: "#34d399" },
  conditional: { label: "Recommended with conditions", text: "text-amber-300", bg: "bg-amber-500/15", ring: "ring-amber-400/40", color: "#fbbf24" },
  not_recommended: { label: "Not recommended", text: "text-rose-300", bg: "bg-rose-500/15", ring: "ring-rose-400/40", color: "#fb7185" },
  insufficient_evidence: { label: "Insufficient evidence", text: "text-slate-300", bg: "bg-slate-500/15", ring: "ring-slate-400/40", color: "#94a3b8" },
};

export const STATUS_STYLE: Record<MetricStatus, { label: string; cls: string; color: string }> = {
  strong: { label: "Strong", cls: "bg-emerald-500/15 text-emerald-300 ring-emerald-400/30", color: "#34d399" },
  adequate: { label: "Adequate", cls: "bg-teal-500/15 text-teal-300 ring-teal-400/30", color: "#2dd4bf" },
  weak: { label: "Weak", cls: "bg-amber-500/15 text-amber-300 ring-amber-400/30", color: "#fbbf24" },
  blocker: { label: "Blocker", cls: "bg-rose-500/15 text-rose-300 ring-rose-400/30", color: "#fb7185" },
  unknown: { label: "Unknown", cls: "bg-slate-500/15 text-slate-300 ring-slate-400/30", color: "#64748b" },
};

export const COMPLIANCE_STYLE: Record<string, { label: string; cls: string }> = {
  pass: { label: "Pass", cls: "bg-emerald-500/15 text-emerald-300 ring-emerald-400/30" },
  risk: { label: "Risk", cls: "bg-amber-500/15 text-amber-300 ring-amber-400/30" },
  fail: { label: "Fail", cls: "bg-rose-500/15 text-rose-300 ring-rose-400/30" },
  unknown: { label: "Unknown", cls: "bg-slate-500/15 text-slate-300 ring-slate-400/30" },
};

export const SEVERITY_STYLE: Record<string, string> = {
  high: "bg-rose-500/15 text-rose-300 ring-rose-400/30",
  medium: "bg-amber-500/15 text-amber-300 ring-amber-400/30",
  low: "bg-slate-500/15 text-slate-300 ring-slate-400/30",
};

export const AGENT_META: Record<AgentName, { label: string; short: string; color: string; icon: string; role: string }> = {
  vexcel: { label: "Vexcel Agent", short: "Vexcel", color: "#22d3ee", icon: "🛰", role: "Building characteristics from aerial AI" },
  neighborhood: { label: "Neighborhood Agent", short: "Neighborhood", color: "#a78bfa", icon: "🏙", role: "Surroundings, demand & competition" },
  compliance: { label: "Compliance Agent", short: "Compliance", color: "#f472b6", icon: "⚖", role: "Permitted use, parking, codes" },
  cost: { label: "Cost Agent", short: "Cost", color: "#fbbf24", icon: "＄", role: "Rent, fit-out & feasibility" },
  matterport: { label: "Matterport Agent", short: "Matterport", color: "#60a5fa", icon: "◫", role: "Interior layout (optional)" },
  engine: { label: "Orchestrator", short: "Engine", color: "#2dd4bf", icon: "◎", role: "Plans, validates, reconciles" },
};

const PALETTE = ["#22d3ee", "#a78bfa", "#f472b6", "#fbbf24", "#34d399", "#60a5fa", "#fb923c", "#e879f9", "#a3e635", "#f87171", "#38bdf8", "#facc15"];

/** Stable color for an arbitrary label (place groups, building types from config). */
export function colorFor(label: string | null | undefined): string {
  const s = label ?? "unknown";
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

const BUILDING_COLORS: Record<string, string> = {
  commercial: "#2dd4bf",
  single_family: "#fbbf24",
  multiple_family: "#fb923c",
  condo_apartment: "#f472b6",
  mobile_home: "#a3e635",
  industrial: "#60a5fa",
};
export const buildingColor = (t: string | null | undefined) => BUILDING_COLORS[t ?? ""] ?? colorFor(t);

export const roofLabel = (c: number | null | undefined) =>
  c == null ? null : ["", "Bad", "Poor", "Fair", "Good", "Great"][Math.max(1, Math.min(5, Math.round(c)))];
