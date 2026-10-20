// Browser journeys through both portals, Keycloak and the API (integration plan I7).
// Needs the compose services, a seeded database, the API and both portals running:
//   npm run test:e2e   (defaults to the local ports; override with CUSTOMER_URL / STAFF_URL)
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  workers: 1, // staff one-time codes are single-use per period; keep sign-ins sequential
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never", outputFolder: "var/e2e-report" }]] : "list",
  outputDir: "var/e2e-results",
  use: {
    ...devices["Desktop Chrome"],
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
