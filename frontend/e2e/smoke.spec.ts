import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/**
 * Collects console errors and uncaught exceptions: a healthy page has none.
 * `expected404` names one URL that may legitimately answer 404 (browsers always log it).
 */
function watchErrors(page: Page, expected404?: string): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const url = message.location().url;
    if (expected404 && url.endsWith(expected404) && message.text().includes("404")) return;
    errors.push(`${message.text()} (${url})`);
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

/** WCAG 2 A/AA audit; serious and critical findings fail the test. */
async function expectAccessible(page: Page): Promise<void> {
  const audit = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = audit.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id}: ${v.help} [${v.nodes.map((n) => n.target.join(" ")).join(", ")}]`);
  expect(serious).toEqual([]);
}

const PAGES: [path: string, title: string][] = [
  ["/", "Overview"],
  ["/runs", "Runs"],
  ["/compare", "Compare"],
  ["/trends", "Trends & drift"],
  ["/baselines", "Baselines & prompts"],
];

for (const [path, title] of PAGES) {
  for (const scheme of ["light", "dark"] as const) {
    test(`${title} (${scheme}): renders, no console errors, accessible`, async ({ page }) => {
      const errors = watchErrors(page);
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
      await page.waitForLoadState("networkidle");
      await expectAccessible(page);
      expect(errors).toEqual([]);
    });
  }
}

test("a run opens from the list and shows a case in detail", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/runs");
  const firstRun = page.getByRole("table").getByRole("link").first();
  const runId = await firstRun.textContent();
  await firstRun.click();
  await expect(page).toHaveURL(new RegExp(`/runs/${runId}$`));
  await expect(page.getByRole("heading", { level: 1, name: /^Run / })).toBeVisible();
  await page.getByRole("button", { name: "Show details" }).first().click();
  await expect(page.getByText("Model answer")).toBeVisible();
  await expectAccessible(page);
  expect(errors).toEqual([]);
});

test("compare a run with the baseline gives a verdict", async ({ page, request }) => {
  const runs = (await (await request.get("/api/runs?limit=1&status=completed")).json()) as {
    items: { run_id: string }[];
  };
  test.skip(runs.items.length === 0, "no completed run in this history");
  const baseline = (await (await request.get("/api/baselines/main")).json()) as {
    source_run_id: string;
  };
  // The baseline's source run may be missing from this history (e.g. CI's seeded one):
  // the page asks for it and shows "Run not in the history database".
  const errors = watchErrors(page, `/api/runs/${baseline.source_run_id}`);
  await page.goto(`/compare?candidate=${runs.items[0]!.run_id}`);
  await expect(page.getByText("Why this verdict")).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "Compare" })).toBeVisible();
  await expectAccessible(page);
  expect(errors).toEqual([]);
});

test("the theme choice applies and survives a reload", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  await page.getByRole("button", { name: "Colour theme" }).click();
  await page.getByRole("menuitemradio", { name: "Dark" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).toHaveClass(/dark/); // applied before first paint
});

test("a deep link with filters survives a reload; unknown pages say so", async ({ page }) => {
  await page.goto("/trends?metric=schema_valid");
  await expect(page.getByRole("heading", { level: 2, name: "Valid format" }).or(page.getByText("Valid format").first())).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Trends & drift" })).toBeVisible();
  await page.goto("/no-such-page");
  await expect(page.getByText("Page not found")).toBeVisible();
});

test("the API refuses foreign host names (DNS rebinding)", async ({ request }) => {
  const response = await request.get("/api/runs", { headers: { Host: "evil.example" } });
  expect(response.status()).toBe(400);
});
