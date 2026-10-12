import { test, expect } from "@playwright/test";

test("visitor can classify a failure, inspect history, and recover", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", {
      name: "Monitor the services your application relies on.",
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Add example services", exact: true })
    .click();
  await expect(page.locator("#feedback")).toContainText("services are ready");
  await expect(page.locator("#integrations .service-row")).toHaveCount(3);
  await page
    .getByRole("button", { name: "Cause outage · 3 checks", exact: true })
    .click();
  await expect(page.locator("#feedback")).toContainText("The incident is open");
  await expect(page.locator("#incidents .status").first()).toHaveText("Open");
  await page.getByText("Explore other failure types", { exact: true }).click();
  await page.getByLabel("Service behavior").selectOption("slow");
  await page
    .getByRole("button", { name: "Apply scenario", exact: true })
    .click();
  await expect(page.locator("#feedback")).toContainText("Scenario applied");
  const payment = page.locator(".service-row").filter({
    has: page.getByRole("link", { name: "Payment API", exact: true }),
  });
  await payment.getByRole("button", { name: "Check now", exact: true }).click();
  await expect(page.locator("#feedback")).toContainText(
    "Check completed: Slow",
  );
  await expect(page.locator("#incidents .status").first()).toHaveText("Open");
  await page
    .getByRole("button", { name: "Restore service · 2 checks", exact: true })
    .click();
  await expect(page.locator("#feedback")).toContainText(
    "The incident is resolved",
  );
  await expect(page.locator("#incidents .status").first()).toHaveText(
    "Resolved",
  );
  await payment.getByRole("link", { name: "Payment API", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Payment API", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.locator("#incidents")).toContainText("Resolved");
  expect(errors).toEqual([]);
});

test("about page explains the project and links directly to source", async ({
  page,
}) => {
  await page.goto("/about");
  await expect(
    page.getByRole("heading", { name: "The problem", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Architecture & tools", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("navigation")
      .getByRole("link", { name: "GitHub ↗", exact: true }),
  ).toHaveAttribute("href", "https://github.com/dpat0103/IntegrationOps");
  for (const width of [320, 390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }
});

test("case study records its complete sequence", async ({ page }) => {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Run the case study", exact: true })
    .click();
  await expect(page.locator("#feedback")).toContainText("Case study complete");
  await expect(page.locator("#case-results .case-result")).toHaveCount(11);
  await expect(page.locator("#case-results")).toContainText(
    "Slow but valid response",
  );
  await expect(page.locator("#incidents .status").first()).toHaveText(
    "Resolved",
  );
  for (const width of [320, 390, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
  }
});

test("connection loss is visible and an invalid service is handled", async ({
  page,
}) => {
  await page.goto("/services/999999");
  await expect(page.locator("#error")).toContainText("not found in your demo");
  await expect(
    page.getByRole("button", { name: "Check now", exact: true }),
  ).toBeDisabled();
  await page.route("**/api/**", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#error")).toContainText(
    "Monitoring data is unavailable",
  );
});
