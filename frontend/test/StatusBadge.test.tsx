import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "@/components/ui/Badge";

describe("StatusBadge", () => {
  it.each([
    ["PASS", "text-pass"],
    ["RISK", "text-risk"],
    ["UNKNOWN", "text-unknown"],
  ] as const)("renders %s with its color", (status, colorClass) => {
    const { container } = render(<StatusBadge status={status} />);
    const label = screen.getByText(status);
    expect(label).toBeInTheDocument();
    expect(label.closest("span")?.className).toContain(colorClass);
    expect(container.querySelector(`[data-status="${status}"]`)).not.toBeNull();
  });

  it("treats an unexpected status as UNKNOWN", () => {
    render(<StatusBadge status="MAYBE" />);
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
  });
});
