import { expect, test } from "@playwright/test";
import { CUSTOMER_URL, STAFF_URL, customerSignIn, staffSignIn } from "./support";

test.describe("membership and administration", () => {
  test("an owner invites a member and revokes the invitation", async ({ page }) => {
    await customerSignIn(page, "owner@acme.test", "/settings");
    const email = `e2e-${Date.now()}@acme.test`;
    await page.getByLabel("Invite by e-mail").fill(email);
    await page.getByRole("button", { name: "Invite" }).click();
    await expect(page.getByText(`Invitation sent to ${email}.`)).toBeVisible();
    const row = page.getByRole("row", { name: new RegExp(email) });
    await expect(row).toContainText("open");
    await row.getByRole("button", { name: "Revoke" }).click();
    await expect(page.getByText(`Revoked the invitation to ${email}.`)).toBeVisible();
    await expect(page.getByRole("row", { name: new RegExp(email) })).toContainText("revoked");
  });

  test("a role change needs confirmation; dismissing it changes nothing", async ({ page }) => {
    await customerSignIn(page, "owner@acme.test", "/settings");
    let asked = "";
    page.once("dialog", (d) => { asked = d.message(); void d.dismiss(); });
    await page.getByLabel("Role for viewer@acme.test").selectOption("owner");
    await expect.poll(() => asked).toContain("Change viewer@acme.test from viewer to owner?");
    const settings = await (await page.request.get(`${CUSTOMER_URL}/api/v1/settings`)).json();
    expect(settings.members.find((m: { user: string }) => m.user === "viewer@acme.test").role).toBe("viewer");
  });

  test("a developer cannot invite, and members are shown read-only", async ({ page }) => {
    await customerSignIn(page, "dev@acme.test", "/settings");
    await expect(page.getByRole("heading", { name: "Members" })).toBeVisible();
    await expect(page.getByLabel("Invite by e-mail")).toHaveCount(0);
    const res = await page.request.post(`${CUSTOMER_URL}/api/v1/invitations`, { data: { email: "x@acme.test", role: "viewer" } });
    expect(res.status()).toBe(403); // no CSRF token from page script, and the role would refuse it anyway
  });

  test("the owner sees who is assigned to the reference application", async ({ page }) => {
    await customerSignIn(page, "owner@acme.test", "/applications/refund-agent/connect");
    await expect(page.getByRole("heading", { name: "Assigned developers" })).toBeVisible();
    await expect(page.getByText("dev@acme.test").first()).toBeVisible();
  });

  test("an admin manages staff roles and sees the workload", async ({ page }) => {
    await staffSignIn(page, "manager@assureops.test", "/admin");
    await expect(page.getByRole("heading", { name: "Workload" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Staff roles" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Revoke Admin for manager@assureops.test" })).toBeDisabled(); // never your own roles
    const res = await page.request.get(`${STAFF_URL}/api/v1/staff/admin/staff`);
    expect(res.status()).toBe(200);
  });

  test("a staff member without the admin role cannot reach staff administration", async ({ page }) => {
    await staffSignIn(page, "operator@assureops.test", "/operations");
    await expect(page.getByRole("link", { name: "Administration" })).toHaveCount(0);
    const res = await page.request.get(`${STAFF_URL}/api/v1/staff/admin/staff`);
    expect(res.status()).toBe(403);
  });
});
