import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnalysisCard } from "@/components/analysis/AnalysisCard";
import { ComparisonTable } from "@/components/analysis/ComparisonTable";
import { formatRange } from "@/lib/format";
import { overlayEvidence } from "@/lib/overlay";
import { analysisFixture } from "./fixtures";

describe("AnalysisCard", () => {
  const top = analysisFixture.results[0];

  it("renders the headline numbers for a property", () => {
    render(<AnalysisCard result={top} />);
    expect(screen.getByRole("heading", { name: top.address })).toBeInTheDocument();
    expect(screen.getByText(`Rank #${top.rank}`)).toBeInTheDocument();
    expect(screen.getAllByText(formatRange(top.total_cost_estimate)).length).toBeGreaterThan(0);
    expect(screen.getByRole("img", { name: `Fit score ${top.score} out of 100` })).toBeInTheDocument();
  });

  it("renders every criterion result with a status badge and line item reasons", () => {
    render(<AnalysisCard result={top} />);
    const rows = screen.getAllByTestId("criterion-result");
    expect(rows).toHaveLength(top.criteria_results.length);
    // Rows are grouped by domain, so match each criterion to its row by description.
    for (const criterion of top.criteria_results) {
      const row = rows.find((r) => within(r).queryByText(criterion.description));
      expect(row, criterion.id).toBeDefined();
      expect(within(row!).getByText(criterion.status)).toBeInTheDocument();
    }
    expect(screen.getByText(top.line_items[0].reason)).toBeInTheDocument();
  });

  it("draws overlay boxes for vexcel and matterport evidence", () => {
    render(<AnalysisCard result={top} />);
    const expected = overlayEvidence(top, "vexcel").length + overlayEvidence(top, "matterport").length;
    const boxes = screen.getAllByTestId("overlay-box");
    expect(boxes).toHaveLength(expected);
    expect(boxes[0].style.left).toMatch(/%$/);
  });

  it("shows landlord questions and the drafted letter", () => {
    render(<AnalysisCard result={top} />);
    expect(screen.getByText(top.questions_for_landlord[0])).toBeInTheDocument();
    expect(screen.getByTestId("landlord-letter").textContent).toContain("Dear Property Manager");
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("flags disqualified properties with their blocking criterion", () => {
    const blocked = analysisFixture.results.find((r) => r.disqualified)!;
    render(<AnalysisCard result={blocked} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Zoning permits the intended use");
    expect(screen.getAllByText("Blocking").length).toBeGreaterThan(0);
  });

  it("shows a Weak fit badge with the min-score explanation only for weak_fit results", () => {
    const weak = analysisFixture.results.find((r) => r.weak_fit)!;
    const { unmount } = render(<AnalysisCard result={weak} minScore={analysisFixture.min_score} />);
    expect(screen.getByText("Weak fit").closest("span")?.className).toContain("text-risk");
    expect(within(screen.getByTestId("weak-fit")).getByRole("tooltip")).toHaveTextContent(
      `Fit score below ${analysisFixture.min_score} — ranked after better-fitting spaces`,
    );
    unmount();

    render(<AnalysisCard result={top} minScore={analysisFixture.min_score} />);
    expect(screen.queryByText("Weak fit")).not.toBeInTheDocument();
  });

  it("treats results from older runs without weak_fit as not weak", () => {
    const legacy = { ...analysisFixture.results.find((r) => r.weak_fit)! };
    delete legacy.weak_fit;
    render(<AnalysisCard result={legacy} />);
    expect(screen.queryByTestId("weak-fit")).not.toBeInTheDocument();
  });
});

describe("ComparisonTable", () => {
  it("renders one column per property in rank order", () => {
    render(<ComparisonTable results={[...analysisFixture.results].reverse()} />);
    const headers = screen.getAllByRole("columnheader").slice(1);
    expect(headers).toHaveLength(analysisFixture.results.length);
    expect(headers[0]).toHaveTextContent("456 Oak Avenue");
    expect(headers[0]).toHaveTextContent("Best value");
    expect(screen.getByText("Disqualified")).toBeInTheDocument();
  });

  it("marks only weak_fit columns with a Weak fit badge next to the rank", () => {
    render(<ComparisonTable results={analysisFixture.results} minScore={analysisFixture.min_score} />);
    const badges = screen.getAllByTestId("weak-fit");
    const weak = analysisFixture.results.filter((r) => r.weak_fit);
    expect(badges).toHaveLength(weak.length);
    expect(badges[0].closest("td")).toHaveTextContent(`#${weak[0].rank}`);
    expect(badges[0]).toHaveTextContent(`Fit score below ${analysisFixture.min_score}`);
  });
});
