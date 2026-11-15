import os from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

// Throwaway SQLite file for the e2e backend so test runs never touch backend/turnkey.db.
// Only used when Playwright starts the backend itself (not when reusing a running server).
const E2E_DB_PATH = path.join(os.tmpdir(), "turnkey-matchmaker-e2e.db");

export default defineConfig({
  testDir: "./e2e",
  // The demo flow runs a real analysis; allow for a cold Next.js dev compile on first visit.
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: { browserName: "chromium", viewport: { width: 1280, height: 800 } },
    },
    {
      name: "mobile",
      use: {
        browserName: "chromium",
        viewport: { width: 375, height: 812 },
        isMobile: true,
        hasTouch: true,
        deviceScaleFactor: 2,
      },
    },
  ],
  webServer: [
    {
      command: "../backend/venv/bin/uvicorn app.main:app --port 8000",
      cwd: "../backend",
      url: "http://localhost:8000/health",
      env: {
        USE_MOCK_DATA: "true",
        DATABASE_URL: `sqlite:///${E2E_DB_PATH}`,
      },
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command: "npm run dev",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "ignore",
      stderr: "pipe",
    },
  ],
});
