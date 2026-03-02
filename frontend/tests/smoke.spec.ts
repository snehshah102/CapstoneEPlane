import { expect, test } from "@playwright/test";

test("landing page renders cinematic hero", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /aerocell makes battery intelligence visible/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /start the experience/i })).toBeVisible();
});

test("experience page renders guided overview", async ({ page }) => {
  await page.goto("/experience");
  await expect(page.getByText(/experience overview/i)).toBeVisible();
  await expect(page.getByText(/how to read this page/i)).toBeVisible();
});

test("planes page navigates into dashboard", async ({ page }) => {
  await page.goto("/planes");
  await expect(page.getByRole("heading", { name: /fleet planes/i })).toBeVisible();
  const dashboardLink = page.getByRole("link", { name: /open dashboard/i }).first();
  await dashboardLink.click();
  await expect(page).toHaveURL(/\/planes\/\d+/);
  await expect(page.getByRole("heading", { name: /plane \d+ dashboard/i })).toBeVisible();
});

test("dashboard shows health meter and calendar", async ({ page }) => {
  await page.goto("/planes/166");
  await expect(page.getByText(/battery health meter/i)).toBeVisible();
  await expect(page.getByText(/calendar view: every day of the month/i)).toBeVisible();
});

test("learn simulator renders interactive controls", async ({ page }) => {
  await page.goto("/learn");
  await expect(page.getByRole("heading", { name: /learn: what drives soh/i })).toBeVisible();
  await expect(page.getByText(/simulation inputs/i)).toBeVisible();
});
