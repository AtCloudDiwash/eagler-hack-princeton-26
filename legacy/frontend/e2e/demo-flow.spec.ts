import { expect, test, type Page, type TestInfo } from "@playwright/test";

// End-to-end coverage of the live demo (docs/DEMO_RUNBOOK.md): profile -> listings -> compare ->
// ranked report. Runs against the real FastAPI backend in mock mode (fixtures/properties.json), so
// the four Austin listings and the zoning disqualification are deterministic.

const DETAILS = "40 seats, kitchen needed, 2 bathrooms, 20 parking spaces";
const AUSTIN_LISTINGS = [
  "123 Elm Street",
  "456 Oak Avenue",
  "789 Congress Avenue, Suite 110",
  "2100 E Cesar Chavez Street",
];

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

test.describe("demo flow", () => {
  test("restaurant in Austin: search, compare 4 spaces, ranked report persists", async ({ page }, testInfo) => {
    // --- Home: business profile ---------------------------------------------------------------
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await page.getByLabel("Business type").selectOption({ label: "Restaurant" });
    await page.getByLabel("What do you need?").fill(DETAILS);
    await page.getByLabel("City or ZIP").fill("Austin");
    await page.getByLabel("State").fill("TX");
    if (isMobile(testInfo)) await expectNoHorizontalOverflow(page, "home");

    await page.getByRole("button", { name: "Find spaces" }).click();

    // --- Properties: the four Austin listings -------------------------------------------------
    await expect(page).toHaveURL(/\/properties\?/);
    await expect(page.getByRole("heading", { level: 1, name: /restaurant in Austin, TX/i })).toBeVisible();
    for (const address of AUSTIN_LISTINGS) {
      await expect(page.getByRole("heading", { level: 3, name: address })).toBeVisible();
    }
    await expect(page.getByRole("checkbox")).toHaveCount(4);
    if (isMobile(testInfo)) await expectNoHorizontalOverflow(page, "properties");

    await page.getByRole("button", { name: "Select all" }).click();
    await expect(page.getByRole("checkbox", { checked: true })).toHaveCount(4);
    if (isMobile(testInfo)) await expectNoHorizontalOverflow(page, "properties (compare bar open)");

    await page.getByRole("button", { name: /Compare 4 selected/ }).click();

    // --- Analysis report ----------------------------------------------------------------------
    await page.waitForURL(/\/analysis\/[^/?#]+$/, { timeout: 60_000 });
    const analysisUrl = page.url();

    await assertReport(page);
    if (isMobile(testInfo)) await expectNoHorizontalOverflow(page, "analysis");

    // --- Reload: the report is read back from SQLite run history ------------------------------
    await page.reload();
    expect(page.url()).toBe(analysisUrl);
    await assertReport(page);
  });

  test("properties page shows an error state with retry when the API fails", async ({ page }) => {
    // Only the listings call fails; /api/v1/criteria and everything else hit the real backend.
    const listingsCall = /\/api\/v1\/properties(\?|$)/;
    await page.route(listingsCall, (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Simulated listings outage" }),
      }),
    );

    await page.goto("/properties?type=restaurant&city=Austin&state=TX");

    const alert = page.getByRole("alert").filter({ hasText: "Couldn't load spaces" });
    await expect(alert).toBeVisible();
    await expect(alert).toContainText("Simulated listings outage");
    const retry = alert.getByRole("button", { name: "Try again" });
    await expect(retry).toBeVisible();

    // Recovery: once the API is healthy again, retry loads the listings.
    await page.unroute(listingsCall);
    await retry.click();
    await expect(alert).toBeHidden();
    await expect(page.getByRole("checkbox")).toHaveCount(4);
  });
});

/** Assertions on a rendered analysis report (used before and after reload). */
async function assertReport(page: Page) {
  const cards = page.getByTestId("analysis-card");
  await expect(cards).toHaveCount(4, { timeout: 30_000 });

  // Rank 1 is 456 Oak Avenue. Cards render sorted by rank, so it is also the first card.
  // Ranks 2-3 are intentionally not asserted: their ordering is still being tuned.
  const topCard = cards.first();
  await expect(topCard.getByText("Rank #1", { exact: true })).toBeVisible();
  await expect(topCard.getByRole("heading", { level: 2 })).toHaveText("456 Oak Avenue");

  // 789 Congress Avenue fails the hard-block zoning criterion.
  const congress = cards.filter({ has: page.getByRole("heading", { level: 2, name: /789 Congress Avenue/ }) });
  await expect(congress).toHaveCount(1);
  await expect(congress.getByText("Disqualified", { exact: true })).toBeVisible();
  const blockedBy = congress.getByRole("alert").filter({ hasText: "Blocked by a hard requirement" });
  await expect(blockedBy).toContainText(/zoning/i);

  // Criteria results carry PASS / RISK / UNKNOWN status badges.
  await expect(page.getByTestId("criterion-result").first()).toBeVisible();
  for (const status of ["PASS", "RISK", "UNKNOWN"]) {
    await expect(page.locator(`[data-testid="criterion-result"] [data-status="${status}"]`).first()).toBeVisible();
  }

  // The Vexcel aerial for the top property actually loads (not the "No aerial image" placeholder).
  const aerial = topCard.getByRole("img", { name: "Aerial view of 456 Oak Avenue" });
  await aerial.scrollIntoViewIfNeeded();
  await expect(aerial).toBeVisible();
  await expect
    .poll(() => aerial.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0))
    .toBe(true);

  // Drafted landlord letter panel is present with real content.
  const letter = topCard.getByTestId("landlord-letter");
  await expect(topCard.getByText("Draft letter to landlord")).toBeVisible();
  await expect(letter).toBeVisible();
  await expect(letter).not.toHaveText("N/A");
}
