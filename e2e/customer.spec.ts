import { expect, test } from "@playwright/test";
import { CUSTOMER_URL, IDP, customerSignIn, submitPassword } from "./support";

test.describe("customer portal", () => {
  test("the BFF refuses API calls without a session", async ({ request }) => {
    const res = await request.get(`${CUSTOMER_URL}/api/v1/applications`);
    expect(res.status()).toBe(401);
  });

  test("an unauthenticated page sends the browser to the customer realm", async ({ page }) => {
    await page.goto(`${CUSTOMER_URL}/overview`);
    await expect(page).toHaveURL(IDP);
    expect(page.url()).toContain("/realms/assureops/");
    expect(page.url()).toContain("code_challenge_method=S256");
  });

  test("a wrong password is rejected at the identity provider", async ({ page }) => {
    await page.goto(`${CUSTOMER_URL}/overview`);
    await submitPassword(page, "dev@acme.test", "not-the-password");
    await expect(page).toHaveURL(IDP);
    await expect(page.getByText(/invalid username or password/i).first()).toBeVisible();
    await expect(page.locator("#password")).toBeVisible();
  });

  test("a developer signs in and sees readiness; tokens never reach the browser", async ({ page, context }) => {
    await customerSignIn(page, "dev@acme.test");
    await expect(page.getByText("AI Application Readiness")).toBeVisible();
    const cookies = await context.cookies(CUSTOMER_URL);
    const session = cookies.find((c) => c.name.includes("session"));
    expect(session?.httpOnly).toBe(true);
    const visible = await page.evaluate(() => document.cookie + JSON.stringify(localStorage) + JSON.stringify(sessionStorage));
    expect(visible).not.toMatch(/eyJ[\w-]+\.eyJ/); // no JWT readable by page scripts
    const apps = await page.request.get(`${CUSTOMER_URL}/api/v1/applications`);
    expect(apps.status()).toBe(200);
  });

  test("the customer BFF never forwards staff or integration routes", async ({ page }) => {
    await customerSignIn(page, "owner@acme.test");
    for (const path of ["v1/staff/cases", "v1/integration/release-gate/check", "v1/runtime/events"]) {
      const res = await page.request.get(`${CUSTOMER_URL}/api/${path}`);
      expect(res.status(), path).toBe(403);
    }
  });

  test("another tenant's application is not readable", async ({ page }) => {
    await customerSignIn(page, "dev@globex.test");
    const own = await page.request.get(`${CUSTOMER_URL}/api/v1/applications/refund-agent/overview`);
    expect([403, 404]).toContain(own.status());
    const forged = await page.request.get(`${CUSTOMER_URL}/api/v1/applications/refund-agent/overview`, { headers: { "x-workspace-id": "acme" } });
    expect([403, 404]).toContain(forged.status());
  });
});
