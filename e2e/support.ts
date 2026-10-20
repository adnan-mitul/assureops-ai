// Shared helpers for the browser journeys. Test values come from the git-ignored dev.env and are never printed.
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, type Page } from "@playwright/test";

export const CUSTOMER_URL = process.env.CUSTOMER_URL ?? "http://localhost:3700";
export const STAFF_URL = process.env.STAFF_URL ?? "http://localhost:3710";
const IDP = /localhost:8780\/realms\//;

let cached: Record<string, string> | undefined;

function devEnv(): Record<string, string> {
  if (!cached) {
    const text = readFileSync(resolve(__dirname, "..", "infra", "compose", "dev.env"), "utf-8");
    cached = Object.fromEntries(
      text.split(/\r?\n/).filter((l) => l && !l.startsWith("#") && l.includes("=")).map((l) => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]),
    );
  }
  return cached;
}

export const password = () => devEnv().DEMO_USER_PASSWORD;

// RFC 6238 TOTP (SHA-1, 30 s, 6 digits), the same as scripts/staff_otp.py.
export function totp(username: string, at = Date.now()): string {
  const secret = devEnv()["STAFF_OTP_" + username.split("@")[0].toUpperCase().replace(/\./g, "_")];
  if (!secret) throw new Error(`no local TOTP secret for ${username}; run scripts/render_realm.py`);
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const digest = createHmac("sha1", Buffer.from(secret)).update(counter).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

// Avoid submitting a code in the last seconds of its period.
async function freshPeriod() {
  const remaining = 30 - (Math.floor(Date.now() / 1000) % 30);
  if (remaining < 6) await new Promise((r) => setTimeout(r, (remaining + 1) * 1000));
}

export async function submitPassword(page: Page, username: string, secret = password()) {
  await expect(page).toHaveURL(IDP);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(secret);
  await page.locator("#kc-login").click();
}

export async function customerSignIn(page: Page, username: string, path = "/overview") {
  await page.goto(`${CUSTOMER_URL}${path}`);
  await submitPassword(page, username);
  await expect(page).toHaveURL(new RegExp(`^${CUSTOMER_URL}`));
}

export async function staffSignIn(page: Page, username: string, path = "/work-queue") {
  await page.goto(`${STAFF_URL}${path}`);
  await submitPassword(page, username);
  await expect(page.locator("#otp")).toBeVisible();
  await freshPeriod();
  await page.locator("#otp").fill(totp(username));
  await page.locator("#kc-login").click();
  await expect(page).toHaveURL(new RegExp(`^${STAFF_URL}`));
}

export { IDP };
