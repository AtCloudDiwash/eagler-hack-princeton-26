import { describe, expect, it } from "vitest";
import { boxToStyle, overlayEvidence } from "@/lib/overlay";
import { analysisFixture } from "./fixtures";

describe("boxToStyle", () => {
  it("converts a normalized box to percentage offsets", () => {
    expect(boxToStyle([0.1, 0.25, 0.5, 0.4])).toEqual({ left: "10%", top: "25%", width: "50%", height: "40%" });
  });

  it("clamps boxes that spill outside the image", () => {
    expect(boxToStyle([0.8, -0.2, 0.5, 2])).toEqual({ left: "80%", top: "0%", width: "20%", height: "100%" });
  });

  it("rounds to two decimals", () => {
    expect(boxToStyle([1 / 3, 0, 1 / 3, 1]).left).toBe("33.33%");
  });
});

describe("overlayEvidence", () => {
  const top = analysisFixture.results[0];

  it("returns only boxed evidence for the requested source, de-duplicated", () => {
    const aerial = overlayEvidence(top, "vexcel");
    const floor = overlayEvidence(top, "matterport");
    expect(aerial.length).toBeGreaterThan(0);
    expect(aerial.every((e) => e.source === "vexcel" && e.box)).toBe(true);
    expect(floor.every((e) => e.source === "matterport" && e.box)).toBe(true);
    const keys = aerial.map((e) => `${e.key}:${e.box.join(",")}`);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("skips evidence without a box", () => {
    const disqualified = analysisFixture.results.find((r) => r.property_id === "property-789")!;
    expect(overlayEvidence(disqualified, "vexcel")).toHaveLength(0);
  });
});
