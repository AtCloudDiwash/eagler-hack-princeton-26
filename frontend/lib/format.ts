// Display formatters. Costs are always shown as ranges ("$84k – $132k"), never as false precision.

import type { CostRange } from "./types";

export const NA = "N/A";

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const integer = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

function isNum(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Full currency: 4000 -> "$4,000". */
export function formatCurrency(value: number | null | undefined): string {
  return isNum(value) ? usd.format(value) : NA;
}

/** Compact currency: 950 -> "$950", 84200 -> "$84k", 1250000 -> "$1.3M". */
export function formatCompactCurrency(value: number | null | undefined): string {
  if (!isNum(value)) return NA;
  const sign = value < 0 ? "-" : "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${sign}$${trimZero((abs / 1_000_000).toFixed(1))}M`;
  if (abs >= 1_000) return `${sign}$${Math.round(abs / 1_000)}k`;
  return `${sign}$${Math.round(abs)}`;
}

function trimZero(text: string): string {
  return text.endsWith(".0") ? text.slice(0, -2) : text;
}

/** Cost range: {min: 84000, max: 132000} -> "$84k – $132k"; equal ends collapse to one value. */
export function formatRange(range: CostRange | null | undefined): string {
  if (!range || !isNum(range.min) || !isNum(range.max)) return NA;
  const low = formatCompactCurrency(range.min);
  const high = formatCompactCurrency(range.max);
  return low === high ? low : `${low} – ${high}`;
}

/** Month range: {min: 2, max: 3} -> "2–3 mo"; {min: 1, max: 1} -> "1 mo". */
export function formatMonths(range: CostRange | null | undefined): string {
  if (!range || !isNum(range.min) || !isNum(range.max)) return NA;
  const low = trimZero(range.min.toFixed(1));
  const high = trimZero(range.max.toFixed(1));
  return low === high ? `${low} mo` : `${low}–${high} mo`;
}

export function formatNumber(value: number | null | undefined, unit?: string): string {
  if (!isNum(value)) return NA;
  return unit ? `${integer.format(value)} ${unit}` : integer.format(value);
}

export function formatSqft(value: number | null | undefined): string {
  return formatNumber(value, "sq ft");
}

/** Monthly rent: 4000 -> "$4,000/mo". */
export function formatRent(value: number | null | undefined): string {
  return isNum(value) ? `${usd.format(value)}/mo` : NA;
}

/** Confidence 0..1 -> "85%". */
export function formatPercent(value: number | null | undefined): string {
  return isNum(value) ? `${Math.round(value * 100)}%` : NA;
}

/** Text fallback: empty/blank -> "N/A". */
export function orNA(value: string | null | undefined): string {
  return value && value.trim() ? value : NA;
}

/** "door_width_inches" -> "Door width inches". */
export function humanize(key: string): string {
  const text = key.replace(/[_-]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : key;
}

/** Arbitrary evidence value -> short display text. */
export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return NA;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return Number.isInteger(value) ? integer.format(value) : String(Number(value.toFixed(2)));
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.length ? value.map(formatValue).join(", ") : NA;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/** ISO timestamp -> "Nov 14, 2026, 3:30 PM" (or N/A if unparseable). */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return NA;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return NA;
  return date.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

const PARKING_SOURCE_LABELS: Record<string, string> = {
  user: "you said",
  guideline: "guideline",
  jurisdiction: "city code",
};

/** Requirements.parking_source -> short label; unknown future sources fall back to humanized text. */
export function parkingSourceLabel(source: string | null | undefined): string {
  if (!source) return "guideline";
  return PARKING_SOURCE_LABELS[source] ?? humanize(source).toLowerCase();
}
