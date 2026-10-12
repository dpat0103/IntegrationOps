import { defineConfig, devices } from "@playwright/test";
const remote = process.env.E2E_BASE_URL;
export default defineConfig({
  testDir: "./tests",
  timeout: 120000,
  expect: { timeout: 15000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: remote ?? "http://127.0.0.1:8765",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1280, height: 900 },
      },
    },
    {
      name: "mobile",
      use: { ...devices["iPhone 13"], browserName: "chromium" },
    },
  ],
  webServer: remote
    ? undefined
    : {
        command: "python -m uvicorn app.main:app --host 127.0.0.1 --port 8765",
        cwd: "..",
        url: "http://127.0.0.1:8765/api/health/live",
        timeout: 60000,
        env: {
          DATABASE_URL: "sqlite:///./e2e-preview.db",
          SCHEDULER_ENABLED: "false",
          AUTO_MIGRATE: "true",
          DEMO_MODE: "true",
          COOKIE_SECURE: "false",
          DEMO_SESSION_SECRET: "browser-test-session-secret-only-local",
        },
      },
});
