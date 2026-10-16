import { defineConfig, devices } from "@playwright/test";

const systemE2e = process.env.E2E_SYSTEM === "1";
const viteServer = {
  command: "node node_modules/vite/bin/vite.js apps/web --host 127.0.0.1 --port 4173 --strictPort",
  env: { VITE_API_BASE_URL: "http://127.0.0.1:8000" },
  reuseExistingServer: !process.env.CI,
  url: "http://127.0.0.1:4173",
};

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    ...devices["Desktop Chrome"],
    channel:
      process.env.PLAYWRIGHT_CHANNEL ?? (process.platform === "win32" ? "chrome" : "chromium"),
  },
  webServer: systemE2e
    ? [
        {
          command: "poetry run python scripts/e2e_fake_llm.py",
          reuseExistingServer: false,
          url: "http://127.0.0.1:8010/health",
        },
        {
          command: "poetry run python -m financial_analytics_api",
          env: {
            APP_ENV: "test",
            CORS_ORIGINS: '["http://127.0.0.1:4173"]',
            SESSION_COOKIE_SECURE: "false",
            TEST_CLOCK_AT: "2026-10-16T20:00:00Z",
            LLM_PROVIDER: "openai_compatible",
            LLM_BASE_URL: "http://127.0.0.1:8010/v1",
            LLM_MODEL: "e2e-deterministic-provider",
            LLM_ENDPOINT_SCOPE: "local",
            LLM_MAX_RETRIES: "0",
          },
          reuseExistingServer: false,
          url: "http://127.0.0.1:8000/health/ready",
        },
        viteServer,
      ]
    : viteServer,
});
