import { describe, expect, it } from "vitest";

import { isProfileResponse, isReadinessResponse } from "./index";

describe("isReadinessResponse", () => {
  it("accepts only the documented ready database state", () => {
    expect(isReadinessResponse({ status: "ready", checks: { database: "up" } })).toBe(true);
    expect(isReadinessResponse({ status: "ready", checks: { database: "down" } })).toBe(false);
    expect(isReadinessResponse({ status: "waiting", checks: { database: "up" } })).toBe(false);
    expect(isReadinessResponse({ status: "ready", checks: null })).toBe(false);
    expect(isReadinessResponse(null)).toBe(false);
  });
});

describe("isProfileResponse", () => {
  it("accepts the documented identity profile without session secrets", () => {
    const profile = {
      id: "018f0000-0000-7000-8000-000000000001",
      email: "master@example.com",
      base_currency: "RUB",
      locale: "ru-RU",
      timezone: "Europe/Saratov",
      status: "active",
      is_master: true,
      created_at: "2026-10-13T00:00:00Z",
    };
    expect(isProfileResponse(profile)).toBe(true);
    expect(isProfileResponse({ ...profile, status: "unknown" })).toBe(false);
    expect(isProfileResponse({ ...profile, is_master: "yes" })).toBe(false);
    expect(isProfileResponse(null)).toBe(false);
  });
});
