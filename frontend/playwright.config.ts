import { defineConfig, devices } from "@playwright/test";

/**
 * Browser smoke tests against a real `regguard serve` (built dashboard + API).
 * CI: Chromium downloaded by Playwright. Locally on Windows: the installed, signed Edge
 * (`npm run e2e -- --project=edge`), since Smart App Control may block downloaded browsers.
 */
const PORT = 4173;
const CONFIG = "../examples/support-email-classifier/regguard.yaml";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "edge", use: { ...devices["Desktop Edge"], channel: "msedge" } },
  ],
  webServer: {
    // uv runs from backend/, so the config path is relative to it.
    command: `uv run --directory ../backend python -m regguard serve --port ${PORT} -c ${CONFIG}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
