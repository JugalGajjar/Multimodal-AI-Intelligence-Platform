import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HealthStatus } from "./health-status";

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

describe("<HealthStatus />", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows probing initially, then renders backend status/version/env", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          status: "ok",
          version: "0.1.0",
          environment: "test",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderWithQuery(<HealthStatus />);

    expect(screen.getByText(/probing/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/Backend ok · v0\.1\.0 · test/)).toBeInTheDocument();
    });
  });

  it("renders an unreachable pill when the request fails", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("nope", {
        status: 500,
        statusText: "Internal Server Error",
      }),
    );

    renderWithQuery(<HealthStatus />);

    await waitFor(() => {
      expect(screen.getByText(/backend unreachable/i)).toBeInTheDocument();
    });
  });

  it("renders an unreachable pill when the network call rejects", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));

    renderWithQuery(<HealthStatus />);

    await waitFor(() => {
      expect(screen.getByText(/backend unreachable/i)).toBeInTheDocument();
    });
  });
});
