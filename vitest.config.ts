import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    coverage: {
      include: [
        "apps/web/src/api.ts",
        "apps/web/src/App.tsx",
        "packages/frontend/api/src/index.ts",
      ],
      provider: "v8",
      reporter: ["text"],
      thresholds: {
        branches: 80,
        functions: 80,
        lines: 80,
        statements: 80,
      },
    },
    environment: "jsdom",
    include: ["apps/web/src/**/*.test.{ts,tsx}", "packages/frontend/api/src/**/*.test.ts"],
    setupFiles: ["./apps/web/test/setup.ts"],
  },
});
