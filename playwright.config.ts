import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    channel:
      process.env.PLAYWRIGHT_CHANNEL ?? (process.platform === "win32" ? "chrome" : "chromium"),
  },
  webServer: {
    command:
      "node node_modules/vite/bin/vite.js apps/web --host 127.0.0.1 --port 4173 --strictPort",
    env: { VITE_API_BASE_URL: "http://127.0.0.1:8000" },
    reuseExistingServer: !process.env.CI,
    url: "http://127.0.0.1:4173",
  },
});
