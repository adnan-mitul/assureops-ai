import { expect, test } from "@playwright/test";
import { IDP, STAFF_URL, staffSignIn, submitPassword } from "./support";

test.describe("staff portal", () => {
  test("the staff BFF refuses API calls without a session", async ({ request }) => {
    const res = await request.get(`${STAFF_URL}/api/v1/staff/work-queue`);
    expect(res.status()).toBe(401);
  });

  test("sign-in always asks the staff realm to re-authenticate", async ({ page }) => {
    await page.goto(`${STAFF_URL}/work-queue`);
    await expect(page).toHaveURL(IDP);
    expect(page.url()).toContain("/realms/assureops-staff/");
    expect(page.url()).toContain("prompt=login");
  });

  test("a password alone is not enough: a wrong one-time code is refused", async ({ page }) => {
    await page.goto(`${STAFF_URL}/work-queue`);
    await submitPassword(page, "reviewer@assureops.test");
    await expect(page.locator("#otp")).toBeVisible();
    await page.locator("#otp").fill("000000");
    await page.locator("#kc-login").click();
    await expect(page).toHaveURL(IDP);
    await expect(page.locator("#otp")).toBeVisible();
  });

  test("customer accounts do not exist in the staff realm", async ({ page }) => {
    await page.goto(`${STAFF_URL}/work-queue`);
    await submitPassword(page, "owner@acme.test");
    await expect(page).toHaveURL(IDP);
    await expect(page.locator("#otp")).toHaveCount(0);
  });

  test("an analyst signs in with password and one-time code and sees the work queue", async ({ page }) => {
    await staffSignIn(page, "analyst@assureops.test");
    await expect(page.getByText("Work queue").first()).toBeVisible();
    const cases = await page.request.get(`${STAFF_URL}/api/v1/staff/work-queue`);
    expect(cases.status()).toBe(200);
    for (const path of ["v1/applications", "v1/integration/release-gate/check"]) {
      const res = await page.request.get(`${STAFF_URL}/api/${path}`);
      expect(res.status(), path).toBe(403); // the staff BFF only forwards staff routes
    }
  });

  test("an operator sees platform operations", async ({ page }) => {
    await staffSignIn(page, "operator@assureops.test", "/operations");
    await expect(page.getByText("Operations").first()).toBeVisible();
    await expect(page.getByText("Outbox").first()).toBeVisible();
  });
});
