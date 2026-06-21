import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // 0 retries keeps a failing nightly under the 30-min job cap so screenshots,
  // traces, and dumped backend logs upload (with retries=2 a single hanging
  // test eats 6 minutes and the whole suite gets cancelled).
  retries: 0,
  workers: process.env.CI ? 1 : undefined,
  // CI tests wait on worker processing — give them headroom.
  timeout: process.env.CI ? 120_000 : 30_000,
  reporter: [
    ["list"],
    ["html", { open: "never" }],
  ],
  use: {
    baseURL: BASE_URL,
    // Always capture trace on failure (was on-first-retry, which never fired
    // with retries=0).
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
