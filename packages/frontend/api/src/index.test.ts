import { afterEach, describe, expect, it, vi } from "vitest";

import { FinancialAnalyticsClient, isProfileResponse, isReadinessResponse } from "./index";

afterEach(() => {
  vi.unstubAllGlobals();
});

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

describe("generated FinancialAnalyticsClient", () => {
  it("serializes exact-money create commands with cookies and idempotency headers", async () => {
    const account = {
      id: "018f0000-0000-7000-8000-000000000001",
      name: "Bank",
      kind: "bank",
      currency: "RUB",
      balance: { amount: "10.00", currency: "RUB" },
      archived: false,
      version: 1,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(account), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const client = new FinancialAnalyticsClient("https://api.example.test");
    await expect(
      client.createAccount({
        idempotencyKey: "account-1",
        xCSRFToken: "csrf-value",
        body: {
          name: "Bank",
          kind: "bank",
          currency: "RUB",
          opening_balance: { amount: "10.00", currency: "RUB" },
        },
      }),
    ).resolves.toEqual(account);

    const [url, options] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.example.test/api/v1/accounts");
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(options.headers).toMatchObject({
      "Idempotency-Key": "account-1",
      "X-CSRF-Token": "csrf-value",
      "Content-Type": "application/json",
    });
  });
});
