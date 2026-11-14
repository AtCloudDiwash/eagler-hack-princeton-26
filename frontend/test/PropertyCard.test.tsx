import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PropertyCard, SAMPLE_LISTING_NOTE } from "@/components/PropertyCard";
import type { Property } from "@/lib/types";

const baseProperty: Property = {
  id: "property-hou-03",
  address: "4720 Washington Avenue",
  city: "Houston",
  state: "TX",
  zip: "77007",
  size_sqft: 2400,
  rent: 7200,
  zoning: null,
  previous_use: "Retail",
  ti_allowance_per_sqft: null,
  latitude: null,
  longitude: null,
  image_url: null,
  matterport_url: null,
  available: true,
};

function renderCard(overrides: Partial<Property> = {}) {
  return render(<PropertyCard property={{ ...baseProperty, ...overrides }} selected={false} onToggle={vi.fn()} />);
}

describe("PropertyCard sample listing badge", () => {
  it('shows the "Sample listing" badge with an explanatory tooltip when listing_source is "sample"', () => {
    renderCard({ listing_source: "sample" });
    const badge = screen.getByTestId("sample-listing-badge");
    expect(badge).toHaveTextContent("Sample listing");
    expect(within(badge).getByRole("button", { name: "About sample listings" })).toBeInTheDocument();
    expect(within(badge).getByRole("tooltip")).toHaveTextContent(SAMPLE_LISTING_NOTE);
  });

  it.each([
    ["costar", "costar"],
    ["null", null],
    ["absent (older backend)", undefined],
  ])("hides the badge when listing_source is %s", (_label, source) => {
    renderCard({ listing_source: source });
    expect(screen.queryByTestId("sample-listing-badge")).not.toBeInTheDocument();
    expect(screen.queryByText("Sample listing")).not.toBeInTheDocument();
  });
});

describe("PropertyCard use restrictions", () => {
  it("shows a warning line for a single restriction, humanized", () => {
    renderCard({ use_restrictions: ["no_food_service"] });
    expect(screen.getByTestId("use-restriction")).toHaveTextContent("Use restriction: no food service");
  });

  it("lists several restrictions on one line", () => {
    renderCard({ use_restrictions: ["no_food_service", "no-alcohol"] });
    expect(screen.getByTestId("use-restriction")).toHaveTextContent("Use restrictions: no food service, no alcohol");
  });

  it.each([
    ["an empty list", []],
    ["null", null],
    ["absent", undefined],
  ])("shows no warning line for %s", (_label, restrictions) => {
    renderCard({ use_restrictions: restrictions });
    expect(screen.queryByTestId("use-restriction")).not.toBeInTheDocument();
  });
});
