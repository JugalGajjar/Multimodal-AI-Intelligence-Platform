import { defineConfig, devices } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // 1 retry in CI: covers one-off transients (uvicorn --reload connection
  // blips, brief TCP RSTs) without blowing the 30-min job cap. Was 0 while
  // we hunted a deterministic OTel/CORS bug — retries don't help there and
  // 2 retries × 4 hangs cancelled the whole suite.
  retries: process.env.CI ? 1 : 0,
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
