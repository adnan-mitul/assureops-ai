// Full product journey with fresh customer accounts (plan v6 P8 "Done"): public inquiry -> staff converts it ->
// a new owner registers, accepts and invites a developer -> owner assigns the developer -> developer connects,
// profiles and submits a release -> assessment -> case -> analyst drafts -> independent reviewer publishes ->
// owner reads the report. No database edits, no impersonation. Mutations without a dedicated screen go through the
// signed-in browser session's BFF (same CSRF-protected path the UI uses); UI steps are clicked.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { CUSTOMER_URL, IDP, STAFF_URL, password, staffSignIn } from "./support";

test.setTimeout(15 * 60_000);

const MAIL = resolve(__dirname, "..", "var", "mail");
const VIDEOS = resolve(__dirname, "..", "var", "e2e-videos"); // one recording per person; kept as the demonstration of a live run
const contexts: BrowserContext[] = [];

async function person(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ recordVideo: { dir: VIDEOS, size: { width: 1280, height: 800 } }, viewport: { width: 1280, height: 800 } });
  contexts.push(context);
  return context.newPage();
}

test.afterAll(async () => {
  test.setTimeout(300_000); // closing writes the recordings, which takes a while on a busy machine
  await Promise.all(contexts.map((c) => c.close()));
});
const RUN = Date.now().toString(36);
const TARGET = process.env.JOURNEY_TARGET_URL ?? "http://127.0.0.1:8710"; // any HTTP/JSON app with /health and /manifest

async function bff<T = unknown>(page: Page, method: string, path: string, body?: unknown): Promise<T> {
  const res = await page.evaluate(async ([m, p, b]) => {
    const csrf = document.cookie.split("; ").find((c) => c.startsWith("ao_csrf_"))?.split("=")[1] ?? "";
    const r = await fetch(`/api${p}`, { method: m as string, headers: { "Content-Type": "application/json", "x-csrf-token": decodeURIComponent(csrf) },
      body: b === undefined ? undefined : JSON.stringify(b) });
    return { status: r.status, text: await r.text() };
  }, [method, path, body] as const);
  expect(res.status, `${method} ${path}: ${res.text}`).toBeLessThan(300);
  return JSON.parse(res.text || "{}") as T;
}

async function inviteToken(email: string): Promise<string> {
  for (let i = 0; i < 60; i++) {  // the dispatcher delivers the notification outbox to the local mail drop
    const files = (() => { try { return readdirSync(MAIL); } catch { return []; } })()
      .map((f) => resolve(MAIL, f)).sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
    for (const f of files.slice(0, 50)) {
      // quoted-printable body: drop soft line breaks and decode =XX escapes
      const text = readFileSync(f, "utf-8").replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/g, (_, hex: string) => String.fromCharCode(parseInt(hex, 16)));
      const token = text.match(/token=(aoinv_[\w-]+)/)?.[1];
      if (text.includes(email) && token) return token;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error(`no invitation e-mail for ${email}`);
}

/** A person who has never used AssureOps: self-registers at the identity provider, then accepts the invitation. */
async function newMember(browser: Browser, email: string, first: string): Promise<Page> {
  const page = await person(browser);
  await page.goto(`${CUSTOMER_URL}/invitations/accept?token=${await inviteToken(email)}`);
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page).toHaveURL(IDP); // not signed in yet
  await page.getByRole("link", { name: /register/i }).click();
  await page.locator("#firstName").fill(first);
  await page.locator("#lastName").fill("Journey");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password());
  await page.locator("#password-confirm").fill(password());
  await page.locator("input[type=submit], button[type=submit]").first().click();
  await expect(page).toHaveURL(/\/invitations\/accept\?token=/); // the token survived the sign-in round trip
  await page.waitForLoadState("networkidle"); // the page must be interactive after the redirect before it is clicked
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await expect(page.getByText("You joined workspace")).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Open the portal" }).click();
  return page;
}

test("fresh customer accounts and staff complete the whole journey", async ({ browser }) => {
  const company = `Journey Labs ${RUN}`;
  const ownerEmail = `owner-${RUN}@journey.test`;
  const devEmail = `dev-${RUN}@journey.test`;
  const workspace = `journey-${RUN}`;
  const appId = `jrn-${RUN}`;

  // 1. A visitor sends the public inquiry (no account, no sign-in).
  const visitor = await person(browser);
  await visitor.goto(`${CUSTOMER_URL}/contact`);
  await visitor.getByLabel("Company").fill(company);
  await visitor.getByLabel("Work e-mail").fill(ownerEmail);
  await visitor.getByLabel("What should we assess?").fill("Please assess our support agent before launch.");
  await visitor.getByRole("button", { name: "Send inquiry" }).click();
  await expect(visitor.getByText("Your inquiry was received")).toBeVisible();

  // 2. A case manager converts it into a workspace; the contact is invited as owner.
  const manager = await person(browser);
  await staffSignIn(manager, "manager@assureops.test", "/admin");
  await manager.getByLabel(`Workspace id for ${company}`).fill(workspace);
  await manager.getByRole("listitem").filter({ hasText: company }).getByRole("button", { name: "Create workspace and invite owner" }).click();
  await expect(manager.getByText(`Workspace ${workspace} created`)).toBeVisible();

  // 3. The new owner registers, joins, and invites a developer from Settings.
  const owner = await newMember(browser, ownerEmail, "Owner");
  await owner.goto(`${CUSTOMER_URL}/settings`);
  await owner.getByLabel("Invite by e-mail").fill(devEmail);
  await owner.getByRole("button", { name: "Invite" }).click();
  await expect(owner.getByText(`Invitation sent to ${devEmail}.`)).toBeVisible();
  const dev = await newMember(browser, devEmail, "Developer");

  // 4. The owner registers the application and assigns the developer to it.
  await bff(owner, "POST", "/v1/applications", { id: appId, name: "Journey support agent", purpose: "Answers support questions",
    environment: "staging", mode: "observe_only" });
  await owner.goto(`${CUSTOMER_URL}/applications/${appId}/connect`);
  await owner.getByLabel("Developer").selectOption({ label: `Developer Journey (${devEmail})` });
  await owner.getByRole("button", { name: "Assign" }).click();
  await expect(owner.getByText(`Assigned ${devEmail}.`)).toBeVisible();

  // 5. The developer connects and verifies the target, proposes a profile; the owner (a different person) activates it.
  await bff(dev, "POST", `/v1/applications/${appId}/connection`, { adapter_id: "assureops-http-json-v1", actors: {},
    config: { base_url: TARGET, environment: "staging", manifest_path: "/manifest", health_path: "/health", scope: { allowed_paths: ["/health"] },
      ownership: { method: "manifest_application" } } });
  await bff(dev, "POST", `/v1/applications/${appId}/connection/verify`);
  const profile = { profile_id: `journey-${RUN}`, version: "1.0.0", catalog: "agentops-controls-v1", adapter: "assureops-http-json-v1",
    requirements: { self_approval_allowed: false }, gate_policy: { version: "1", blocking_severities: ["critical", "high"] }, evidence_freshness_days: 30,
    tests: [{ id: "J-ID", control: "C10", severity: "high", trials: 1, name: "Running release matches the manifest", expected: "same release",
      template: "manifest_identity", args: {}, mandatory: true }] };
  const proposed = await bff<{ revision: number }>(dev, "POST", `/v1/applications/${appId}/profiles`, { profile });
  await bff(owner, "POST", `/v1/applications/${appId}/profiles/${proposed.revision}/activate`, { note: "Reviewed for the journey" });

  // 6. The developer submits the running release, runs the assessment and opens a case.
  await bff(dev, "POST", `/v1/applications/${appId}/releases`, {});
  const job = await bff<{ id: string }>(dev, "POST", "/v1/assessments", { application_id: appId, scope: "full" });
  await expect.poll(async () => (await bff<{ status: string }>(dev, "GET", `/v1/assessments/${job.id}`)).status, { timeout: 180_000, intervals: [3000] })
    .toBe("completed");
  const kase = await bff<{ id: string }>(dev, "POST", "/v1/customer/cases", { application_id: appId, title: "Pre-launch readiness", scope_note: "Journey test" });

  // 7. Staff: the manager assigns an analyst and an independent reviewer; the analyst drafts; the reviewer publishes.
  await bff(manager, "POST", `/v1/staff/cases/${kase.id}/assignments`, { staff_user: "analyst@assureops.test", duty: "analyst" });
  await bff(manager, "POST", `/v1/staff/cases/${kase.id}/assignments`, { staff_user: "reviewer@assureops.test", duty: "reviewer" });
  const analyst = await person(browser);
  await staffSignIn(analyst, "analyst@assureops.test", `/cases/${kase.id}`);
  await analyst.getByRole("button", { name: "Draft report" }).click();
  await expect(analyst.getByText(/drafted/i).first()).toBeVisible();
  const reviewer = await person(browser);
  await staffSignIn(reviewer, "reviewer@assureops.test", `/cases/${kase.id}/review`);
  await reviewer.getByLabel(/Publish to the customer/).check();
  await reviewer.getByLabel(/Reason/).fill("Snapshot reviewed independently; scope and evidence are as stated.");
  await reviewer.getByRole("button", { name: "Publish report" }).click();
  await expect(reviewer.getByText(/published/i).first()).toBeVisible();

  // 8. The owner reads the published report and can download its evidence bundle.
  await owner.goto(`${CUSTOMER_URL}/reports`);
  const reports = await bff<{ report_id: string; state: string }[]>(owner, "GET", `/v1/reports?application_id=${appId}`);
  const published = reports.find((r) => r.state === "published");
  expect(published).toBeTruthy();
  await owner.goto(`${CUSTOMER_URL}/reports/${published!.report_id}`);
  await expect(owner.getByRole("link", { name: "Evidence bundle" })).toBeVisible();
  await expect(owner.getByText(/not a certification/i).first()).toBeVisible();
  void STAFF_URL;
});
