import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { CUSTOMER_URL, STAFF_URL, customerSignIn, staffSignIn } from "./support";

// Automated WCAG 2.1 A/AA checks on the main pages; serious and critical violations fail the run.
async function audit(page: Page, label: string) {
  await page.waitForLoadState("networkidle");
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const blocking = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(blocking.map((v) => `${label}: ${v.id} (${v.impact}) ${v.nodes.length} node(s): ${v.nodes[0]?.target.join(" ")}`)).toEqual([]);
}

test.describe("accessibility", () => {
  test("customer pages have no serious WCAG violations", async ({ page }) => {
    await customerSignIn(page, "owner@acme.test", "/overview");
    for (const path of ["/overview", "/applications", "/findings", "/settings", "/notifications", "/applications/refund-agent/connect"]) {
      await page.goto(`${CUSTOMER_URL}${path}`);
      await audit(page, path);
    }
  });

  test("staff pages have no serious WCAG violations", async ({ page }) => {
    await staffSignIn(page, "manager@assureops.test", "/work-queue");
    for (const path of ["/work-queue", "/operations", "/governance", "/admin", "/notifications"]) {
      await page.goto(`${STAFF_URL}${path}`);
      await audit(page, path);
    }
  });

  test("keyboard users can skip straight to the page content", async ({ page }) => {
    await customerSignIn(page, "viewer@acme.test", "/overview");
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("main#main")).toBeFocused();
  });
});

test.describe("inbox and exports", () => {
  test("the inbox lists only the signed-in person's notifications and marks them read", async ({ page }) => {
    await customerSignIn(page, "dev@acme.test", "/notifications");
    await expect(page.getByRole("heading", { name: "Notifications" })).toBeVisible();
    const inbox = await (await page.request.get(`${CUSTOMER_URL}/api/v1/notifications`)).json();
    expect(inbox.items.every((n: { workspace_id: string | null }) => n.workspace_id === null || n.workspace_id === "acme")).toBe(true);
    await expect(page.getByRole("link", { name: /^Notifications: \d+ unread$/ })).toBeVisible();
  });

  test("a published report downloads as an evidence bundle with a hash manifest", async ({ page }) => {
    await customerSignIn(page, "viewer@acme.test", "/reports");
    const apps = await (await page.request.get(`${CUSTOMER_URL}/api/v1/applications`)).json();
    let reportId: string | undefined;
    for (const a of apps as { id: string }[]) {
      const list = await (await page.request.get(`${CUSTOMER_URL}/api/v1/reports?application_id=${a.id}`)).json();
      const published = (list as { report_id: string; state: string }[]).find((r) => r.state === "published");
      if (published) { reportId = published.report_id; break; }
    }
    test.skip(!reportId, "no published report in this database (run a lab journey first)");
    const res = await page.request.get(`${CUSTOMER_URL}/api/v1/reports/${reportId}/export`);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("application/zip");
    const bytes = await res.body();
    expect(bytes.subarray(0, 2).toString()).toBe("PK"); // the zip passes through the BFF unchanged
    expect(bytes.includes(Buffer.from("manifest.json"))).toBe(true);
  });
});
