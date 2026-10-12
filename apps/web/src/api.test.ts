import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchReadiness } from "./api";

describe("fetchReadiness", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("accepts a valid response without an AbortSignal", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ready", checks: { database: "up" } }), {
          status: 200,
        }),
      ),
    );

    await expect(fetchReadiness()).resolves.toEqual({
      status: "ready",
      checks: { database: "up" },
    });
  });

  it("rejects a non-success HTTP response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));

    await expect(fetchReadiness()).rejects.toThrow("HTTP 503");
  });

  it("rejects a response outside the API contract", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "almost-ready" }))),
    );

    await expect(fetchReadiness()).rejects.toThrow("does not match the API contract");
  });
});
