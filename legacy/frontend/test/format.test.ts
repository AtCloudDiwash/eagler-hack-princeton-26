import { describe, expect, it } from "vitest";
import {
  formatCompactCurrency,
  formatCurrency,
  formatMonths,
  formatPercent,
  formatRange,
  formatRent,
  formatValue,
  humanize,
  orNA,
} from "@/lib/format";

describe("format helpers", () => {
  it("formats full and compact currency", () => {
    expect(formatCurrency(4000)).toBe("$4,000");
    expect(formatCompactCurrency(950)).toBe("$950");
    expect(formatCompactCurrency(84200)).toBe("$84k");
    expect(formatCompactCurrency(1_250_000)).toBe("$1.3M");
    expect(formatCompactCurrency(2_000_000)).toBe("$2M");
  });

  it("formats cost ranges with an en dash", () => {
    expect(formatRange({ min: 84000, max: 132000 })).toBe("$84k – $132k");
    expect(formatRange({ min: 5000, max: 5000 })).toBe("$5k");
    expect(formatRange(null)).toBe("N/A");
  });

  it("formats month ranges and rent", () => {
    expect(formatMonths({ min: 2, max: 3 })).toBe("2–3 mo");
    expect(formatMonths({ min: 1.5, max: 1.5 })).toBe("1.5 mo");
    expect(formatRent(4800)).toBe("$4,800/mo");
  });

  it("falls back to N/A for missing values", () => {
    expect(formatCurrency(null)).toBe("N/A");
    expect(formatCurrency(Number.NaN)).toBe("N/A");
    expect(orNA("")).toBe("N/A");
    expect(orNA("  ")).toBe("N/A");
    expect(orNA("GR")).toBe("GR");
    expect(formatPercent(undefined)).toBe("N/A");
  });

  it("formats evidence values and keys", () => {
    expect(formatValue(true)).toBe("Yes");
    expect(formatValue(36)).toBe("36");
    expect(formatValue(7.456)).toBe("7.46");
    expect(formatValue(["a", "b"])).toBe("a, b");
    expect(formatValue(null)).toBe("N/A");
    expect(formatPercent(0.854)).toBe("85%");
    expect(humanize("door_width_inches")).toBe("Door width inches");
  });
});
