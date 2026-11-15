import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalysisView } from "@/app/analysis/[id]/AnalysisView";
import { ApiStatus } from "@/components/ApiStatus";
import { ANALYSIS_STEPS, analysisSteps } from "@/components/AnalyzeProgress";
import { AI_SUMMARY_CAVEAT, AiSummaryPanel } from "@/components/analysis/AiSummaryPanel";
import { AnalysisCard } from "@/components/analysis/AnalysisCard";
import { ComparisonTable } from "@/components/analysis/ComparisonTable";
import { RequirementsSummary } from "@/components/analysis/RequirementsSummary";
import { api } from "@/lib/api";
import { llmLabel, parserLabel } from "@/lib/format";
import type { AnalyzeResponse, HealthResponse } from "@/lib/types";
import { analysisFixture } from "./fixtures";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: analysisFixture.analysis_id }) }));

const summary = analysisFixture.ai_summary!;

/** A stored run from before the LLM fields existed: no ai_summary key, no mode.llm, regex parser. */
function legacyRun(): AnalyzeResponse {
  const run: AnalyzeResponse = { ...analysisFixture, mode: { ...analysisFixture.mode, parser: "regex" } };
  delete run.ai_summary;
  delete run.mode.llm;
  return run;
}

afterEach(() => vi.restoreAllMocks());

describe("llmLabel / parserLabel", () => {
  it("labels local, Claude, unknown and missing models", () => {
    expect(llmLabel("ollama:qwen3:8b")).toBe("Local AI · qwen3:8b");
    expect(llmLabel("anthropic:claude-haiku-5-5")).toBe("Claude · claude-haiku-5-5");
    expect(llmLabel("mystery-model")).toBe("AI · mystery-model");
    expect(llmLabel("none")).toBe("No AI");
    expect(llmLabel(undefined)).toBe("No AI");
  });

  it("names the parser actually used", () => {
    expect(parserLabel("regex")).toBe("Regex");
    expect(parserLabel("ollama")).toBe("Ollama");
    expect(parserLabel("claude")).toBe("Claude");
  });
});

describe("AiSummaryPanel", () => {
  it("renders the summary text, model badge and caveat", () => {
    render(<AiSummaryPanel summary={summary} />);
    const panel = screen.getByTestId("ai-summary");
    expect(within(panel).getByRole("heading", { name: /AI summary/ })).toBeInTheDocument();
    expect(panel).toHaveTextContent(summary.text);
    expect(within(panel).getByText("Local AI · qwen3:8b")).toBeInTheDocument();
    expect(within(panel).getByText(AI_SUMMARY_CAVEAT)).toBeInTheDocument();
  });

  it("renders nothing when the summary is null, missing or blank", () => {
    for (const value of [null, undefined, { ...summary, text: "  " }]) {
      const { container, unmount } = render(<AiSummaryPanel summary={value} />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });
});

describe("AI sentences per property", () => {
  const top = analysisFixture.results[0];

  it("shows the one-line reason in the AnalysisCard header", () => {
    render(<AnalysisCard result={top} aiSentence={summary.per_property[top.property_id]} />);
    const header = screen.getByRole("heading", { name: top.address }).closest("header")!;
    expect(within(header).getByTestId("ai-sentence")).toHaveTextContent(summary.per_property[top.property_id]);
  });

  it("omits the sentence when there is none", () => {
    render(<AnalysisCard result={top} />);
    expect(screen.queryByTestId("ai-sentence")).not.toBeInTheDocument();
  });

  it("adds a 'Why (AI)' row to the comparison table only when a summary covers a property", () => {
    const partial = { ...summary, per_property: { [top.property_id]: summary.per_property[top.property_id] } };
    const { unmount } = render(<ComparisonTable results={analysisFixture.results} aiSummary={partial} />);
    const row = screen.getByRole("rowheader", { name: "Why (AI)" }).closest("tr")!;
    const cells = within(row).getAllByRole("cell");
    expect(cells).toHaveLength(analysisFixture.results.length);
    expect(cells[0]).toHaveTextContent(summary.per_property[top.property_id]);
    expect(cells[1]).toHaveTextContent("N/A");
    unmount();

    render(<ComparisonTable results={analysisFixture.results} aiSummary={null} />);
    expect(screen.queryByRole("rowheader", { name: "Why (AI)" })).not.toBeInTheDocument();
  });
});

describe("mode badges", () => {
  it("shows the parser used and the summary model", () => {
    render(<RequirementsSummary analysis={analysisFixture} />);
    const sources = screen.getByLabelText("Data sources");
    expect(within(sources).getByText("parser: Ollama")).toBeInTheDocument();
    expect(within(sources).getByText("Local AI · qwen3:8b")).toBeInTheDocument();
    expect(within(sources).getByText("costar: mock")).toBeInTheDocument();
  });

  it("shows no AI badge for an older run without mode.llm", () => {
    render(<RequirementsSummary analysis={legacyRun()} />);
    const sources = screen.getByLabelText("Data sources");
    expect(within(sources).getByText("parser: Regex")).toBeInTheDocument();
    expect(within(sources).queryByText(/AI/)).not.toBeInTheDocument();
  });
});

describe("AnalysisView with and without ai_summary", () => {
  it("places the AI summary panel above the comparison table", async () => {
    vi.spyOn(api, "analysis").mockResolvedValue(analysisFixture);
    render(<AnalysisView />);
    const panel = await screen.findByTestId("ai-summary");
    const table = screen.getByRole("table");
    expect(panel.compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByTestId("ai-sentence")).toHaveLength(analysisFixture.results.length);
  });

  it("renders an older stored run without ai_summary or mode.llm", async () => {
    vi.spyOn(api, "analysis").mockResolvedValue(legacyRun());
    render(<AnalysisView />);
    expect(await screen.findAllByTestId("analysis-card")).toHaveLength(analysisFixture.results.length);
    expect(screen.queryByTestId("ai-summary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ai-sentence")).not.toBeInTheDocument();
    expect(screen.queryByRole("rowheader", { name: "Why (AI)" })).not.toBeInTheDocument();
  });

  it("hides the panel when ai_summary is null", async () => {
    vi.spyOn(api, "analysis").mockResolvedValue({ ...analysisFixture, ai_summary: null });
    render(<AnalysisView />);
    await screen.findAllByTestId("analysis-card");
    expect(screen.queryByTestId("ai-summary")).not.toBeInTheDocument();
  });
});

describe("local AI status", () => {
  const health = (llm?: string): HealthResponse => ({
    status: "ok",
    mode: { costar: "mock", matterport: "mock", vexcel: "live", parser: "ollama", ...(llm ? { llm } : {}) },
  });

  it("header pill says Local AI ready for an Ollama model and ignores parser/llm for mock/live", async () => {
    vi.spyOn(api, "health").mockResolvedValue(health("ollama:qwen3:8b"));
    render(<ApiStatus />);
    expect(await screen.findByTestId("local-ai-ready")).toHaveTextContent("Local AI ready");
    expect(screen.getByText(/mixed data/)).toBeInTheDocument();
  });

  it("header pill has no AI note when llm is none or absent", async () => {
    vi.spyOn(api, "health").mockResolvedValue(health("none"));
    render(<ApiStatus />);
    await screen.findByText(/mixed data/);
    expect(screen.queryByTestId("local-ai-ready")).not.toBeInTheDocument();
  });

  it("adds a 'Writing summary' progress step only when an LLM is configured", () => {
    expect(analysisSteps("ollama:qwen3:8b").at(-1)).toBe("Writing summary (local AI)");
    expect(analysisSteps("anthropic:claude-haiku-5-5").at(-1)).toBe("Writing summary (AI)");
    expect(analysisSteps("none")).toEqual(ANALYSIS_STEPS);
    expect(analysisSteps(undefined)).toEqual(ANALYSIS_STEPS);
  });
});
