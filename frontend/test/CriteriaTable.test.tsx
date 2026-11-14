import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CriteriaTable } from "@/components/CriteriaTable";
import type { Criterion } from "@/lib/types";

/** Arbitrary criteria with made-up ids: the table must not depend on any known criterion. */
function makeCriteria(count: number): Criterion[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `custom_rule_${i}`,
    description: `Custom rule number ${i}`,
    domain: i % 2 === 0 ? "space" : "brand_new_domain",
    weight: i + 1,
    hard_block: i === 0,
    evaluator: "threshold_check",
    required_inputs: ["size_sqft"],
    missing_data_policy: "unknown",
    evidence_required: false,
    source: `Ordinance ${i}`,
    thresholds: { min: i },
    business_types: ["any"],
    applicable_jurisdictions: [],
  }));
}

describe("CriteriaTable (registry-driven)", () => {
  it.each([1, 7, 23])("renders one row per criterion (%i)", (count) => {
    render(<CriteriaTable criteria={makeCriteria(count)} />);
    expect(screen.getAllByTestId("criterion-row")).toHaveLength(count);
    expect(screen.getByText(`custom_rule_${count - 1}`)).toBeInTheDocument();
  });

  it("shows description, domain, weight, hard block and source", () => {
    render(<CriteriaTable criteria={makeCriteria(2)} />);
    expect(screen.getByText("Custom rule number 1")).toBeInTheDocument();
    expect(screen.getAllByText("Brand new domain").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Yes")).toHaveLength(1); // only criterion 0 is a hard block
    expect(screen.getAllByText("Ordinance 1").length).toBeGreaterThan(0);
  });

  it("handles an empty registry", () => {
    render(<CriteriaTable criteria={[]} />);
    expect(screen.getByText(/No criteria apply/)).toBeInTheDocument();
  });
});
