import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AnalysisCard } from "@/components/analysis/AnalysisCard";
import { MediaPanel } from "@/components/analysis/MediaPanel";
import { RequirementsSummary } from "@/components/analysis/RequirementsSummary";
import { parkingSourceLabel } from "@/lib/format";
import type { AnalysisResult } from "@/lib/types";
import { analysisFixture } from "./fixtures";

const liveResult = analysisFixture.results.find((r) => r.media.aerial_source === "vexcel-live")!;
const placeholderResult = analysisFixture.results[0];

describe("MediaPanel imagery source", () => {
  it("shows the Live · Vexcel badge and attribution for live imagery", () => {
    render(<MediaPanel result={liveResult} />);
    expect(screen.getByTestId("aerial-live")).toHaveTextContent("Live · Vexcel");
    expect(screen.getByTestId("aerial-attribution")).toHaveTextContent("© Vexcel Imaging US, Inc.");
    expect(screen.queryByText("Placeholder imagery")).not.toBeInTheDocument();
  });

  it("labels placeholder imagery and shows no live badge or attribution", () => {
    render(<MediaPanel result={placeholderResult} />);
    expect(screen.getByText("Placeholder imagery")).toBeInTheDocument();
    expect(screen.queryByTestId("aerial-live")).not.toBeInTheDocument();
    expect(screen.queryByTestId("aerial-attribution")).not.toBeInTheDocument();
  });

  it("falls back to a Vexcel attribution when live imagery has none", () => {
    const noAttribution = { ...liveResult, media: { ...liveResult.media, aerial_attribution: null } };
    render(<MediaPanel result={noAttribution} />);
    expect(screen.getByTestId("aerial-attribution")).toHaveTextContent(/Vexcel/);
  });
});

describe("MediaPanel angled view", () => {
  it("offers Top-down / Angled tabs when oblique_url is set; overlays stay on the top-down view", () => {
    render(<MediaPanel result={liveResult} />);
    const tabs = within(screen.getByRole("tablist", { name: "Aerial view" })).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Top-down", "Angled"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("img", { name: `Aerial view of ${liveResult.address}` })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: `Angled aerial view of ${liveResult.address}` })).not.toBeInTheDocument();

    fireEvent.click(tabs[1]);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    const angled = screen.getByRole("img", { name: `Angled aerial view of ${liveResult.address}` });
    expect(angled).toHaveAttribute("src", liveResult.media.oblique_url);
    expect(angled).toHaveAttribute("loading", "lazy");
    // The overlay boxes live in the (now hidden) top-down panel only.
    expect(within(screen.getByRole("tabpanel")).queryAllByTestId("overlay-box")).toHaveLength(0);
  });

  it("renders no tabs or angled image when oblique_url is null", () => {
    render(<MediaPanel result={{ ...liveResult, media: { ...liveResult.media, oblique_url: null } }} />);
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByText("Angled")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: `Aerial view of ${liveResult.address}` })).toBeInTheDocument();
  });

  it("draws the building footprint box on the aerial with its label", () => {
    render(<MediaPanel result={liveResult} />);
    const footprint = screen.getAllByTestId("overlay-box").find((box) => box.dataset.footprint);
    expect(footprint).toBeDefined();
    expect(footprint).toHaveTextContent("Building footprint");
    expect(footprint!.style.width).toBe("60%");
  });
});

describe("live evidence", () => {
  it("marks live evidence in the criteria and observations, but not fixture evidence", () => {
    render(<AnalysisCard result={liveResult} />);
    const liveCount = Object.values(liveResult.observations).filter((e) => e.live).length;
    expect(screen.getAllByTestId("live-evidence").length).toBeGreaterThanOrEqual(liveCount);
    const parkingRow = screen
      .getAllByTestId("criterion-result")
      .find((row) => within(row).queryByText("Enough off-street parking for the use"))!;
    expect(within(parkingRow).getByTestId("live-evidence")).toBeInTheDocument();
    expect(within(parkingRow).getByText(/82%/)).toBeInTheDocument();
  });

  it("shows no live markers for a mock-mode result", () => {
    render(<AnalysisCard result={placeholderResult} />);
    expect(screen.queryByTestId("live-evidence")).not.toBeInTheDocument();
  });
});

describe("older stored runs", () => {
  it("renders a result without the Vexcel media fields or evidence.live", () => {
    const { oblique_url, aerial_source, aerial_attribution, ...legacyMedia } = liveResult.media;
    void oblique_url;
    void aerial_source;
    void aerial_attribution;
    const strip = <T extends { live?: boolean }>(e: T) => {
      const copy = { ...e };
      delete copy.live;
      return copy;
    };
    const legacy: AnalysisResult = {
      ...liveResult,
      media: legacyMedia,
      observations: Object.fromEntries(Object.entries(liveResult.observations).map(([k, e]) => [k, strip(e)])),
      criteria_results: liveResult.criteria_results.map((c) => ({ ...c, evidence: c.evidence.map(strip) })),
    };
    render(<AnalysisCard result={legacy} />);
    expect(screen.getByRole("heading", { name: legacy.address })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: `Aerial view of ${legacy.address}` })).toBeInTheDocument();
    expect(screen.getByText("Placeholder imagery")).toBeInTheDocument();
    expect(screen.queryByTestId("aerial-live")).not.toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByTestId("live-evidence")).not.toBeInTheDocument();
  });
});

describe("parking source label", () => {
  it("maps known sources and humanizes unknown ones", () => {
    expect(parkingSourceLabel("user")).toBe("you said");
    expect(parkingSourceLabel("guideline")).toBe("guideline");
    expect(parkingSourceLabel("jurisdiction")).toBe("city code");
    expect(parkingSourceLabel("traffic_study")).toBe("traffic study");
  });

  it("labels a jurisdiction parking minimum as city code in the requirements summary", () => {
    const analysis = {
      ...analysisFixture,
      requirements: { ...analysisFixture.requirements, parking_source: "jurisdiction" },
    };
    render(<RequirementsSummary analysis={analysis} />);
    expect(screen.getByText("Parking (city code)")).toBeInTheDocument();
  });
});
