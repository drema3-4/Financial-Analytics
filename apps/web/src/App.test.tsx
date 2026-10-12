import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reports that the core API is ready after a valid readiness response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ready", checks: { database: "up" } }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    render(<App />);

    expect(screen.getByRole("heading", { name: "Financial Analytics" })).toBeInTheDocument();
    expect(await screen.findByRole("status")).toHaveTextContent("Core API готов");
  });

  it("shows an unavailable state when the API request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network unavailable")));

    render(<App />);

    expect(await screen.findByRole("status")).toHaveTextContent("Core API недоступен");
  });
});
