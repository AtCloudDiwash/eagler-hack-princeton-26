import { expect, test, type Page, type TestInfo } from "@playwright/test";

// Houston demo flow (docs/DEMO_RUNBOOK.md) against the real FastAPI backend in mock mode
// (backend/fixtures/properties.json). Houston listings are "sample" records: real buildings with
// illustrative rent/size. Houston has no zoning ordinance, so the zoning criterion says so, and
// 4720 Washington Avenue is disqualified by its recorded "no food service" use restriction.
// Parking/HVAC note texts are deliberately not asserted (still being tuned on the backend).

const DETAILS = "40 seats, kitchen needed, 2 bathrooms";
const SELECTED_LISTINGS = [
  "1903 Yale Street",
  "240 W 19th Street",
  "4720 Washington Avenue",
  "801 St Emanuel Street",
];
const UNSELECTED_LISTING = "3701 Kirby Drive";

const isMobile = (testInfo: TestInfo) => testInfo.project.name === "mobile";

/** Fails if the page scrolls horizontally (1px tolerance for sub-pixel rounding). */
async function expectNoHorizontalOverflow(page: Page, label: string) {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(scrollWidth, `${label}: scrollWidth ${scrollWidth}px vs innerWidth ${innerWidth}px`).toBeLessThanOrEqual(
    innerWidth + 1,
  );
}

test.describe("Houston demo flow", () => {
  test("restaurant in Houston: compare 4 sample listings, use restriction disqualifies, no-zoning note", async ({
    page,
  }, testInfo) => {
    // --- Home: business profile ---------------------------------------------------------------
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.getByLabel("Business type").selectOption({ label: "Restaurant" });
    await page.getByLabel("What do you need?").fill(DETAILS);
    await page.getByLabel("City or ZIP").fill("Houston");
    await page.getByLabel("State").fill("TX");
    await page.getByRole("button", { name: "Find spaces" }).click();

    // --- Properties: five Houston sample listings ---------------------------------------------
    await expect(page).toHaveURL(/\/properties\?/);
    await expect(page.getByRole("heading", { level: 1, name: /restaurant in Houston, TX/i })).toBeVisible();
    for (const address of [...SELECTED_LISTINGS, UNSELECTED_LISTING]) {
      await expect(page.getByRole("heading", { level: 3, name: address })).toBeVisible();
    }
    await expect(page.getByTestId("sample-listing-badge").first()).toBeVisible();
    await expect(page.getByTestId("sample-listing-badge").first()).toContainText("Sample listing");

    const washingtonCard = page.locator("label").filter({
      has: page.getByRole("heading", { level: 3, name: "4720 Washington Avenue" }),
    });
    await expect(washingtonCard.getByTestId("use-restriction")).toContainText(/use restriction: no food service/i);
    if (isMobile(testInfo)) await expectNoHorizontalOverflow(page, "properties");

    // Select the four listings by clicking their cards (Kirby stays unselected).
    for (const address of SELECTED_LISTINGS) {
      await page.getByRole("heading", { level: 3, name: address }).click();
    }
    await expect(page.getByRole("checkbox", { checked: true })).toHaveCount(4);
    await expect(page.getByRole("checkbox", { name: new RegExp(UNSELECTED_LISTING) })).not.toBeChecked();

    await page.getByRole("button", { name: /Compare 4 selected/ }).click();

    // --- Analysis report ----------------------------------------------------------------------
    await page.waitForURL(/\/analysis\/[^/?#]+$/, { timeout: 60_000 });

    const cards = page.getByTestId("analysis-card");
    await expect(cards).toHaveCount(4, { timeout: 30_000 });

    const topCard = cards.first();
    await expect(topCard.getByText("Rank #1", { exact: true })).toBeVisible();
    await expect(topCard.getByRole("heading", { level: 2 })).toHaveText("1903 Yale Street");

    const washington = cards.filter({ has: page.getByRole("heading", { level: 2, name: /4720 Washington Avenue/ }) });
    await expect(washington).toHaveCount(1);
    await expect(washington.getByText("Disqualified", { exact: true })).toBeVisible();

    // Houston has no zoning ordinance: the zoning criterion result says so.
    await expect(page.getByTestId("criterion-result").filter({ hasText: /no zoning/i }).first()).toBeVisible();

    if (isMobile(testInfo)) await expectNoHorizontalOverflow(page, "analysis");
  });
});
