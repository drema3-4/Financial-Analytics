import { describe, expect, it } from "vitest";

import { isReadinessResponse } from "./index";

describe("isReadinessResponse", () => {
  it("accepts only the documented ready database state", () => {
    expect(isReadinessResponse({ status: "ready", checks: { database: "up" } })).toBe(true);
    expect(isReadinessResponse({ status: "ready", checks: { database: "down" } })).toBe(false);
    expect(isReadinessResponse({ status: "waiting", checks: { database: "up" } })).toBe(false);
    expect(isReadinessResponse({ status: "ready", checks: null })).toBe(false);
    expect(isReadinessResponse(null)).toBe(false);
  });
});
