import { spawnSync } from "node:child_process";
import process from "node:process";

const result = spawnSync(
  process.execPath,
  [
    "node_modules/@playwright/test/cli.js",
    "test",
    "tests/e2e/system-scenarios.spec.ts",
    ...process.argv.slice(2),
  ],
  {
    env: { ...process.env, E2E_SYSTEM: "1" },
    stdio: "inherit",
  },
);

process.exit(result.status ?? 1);
