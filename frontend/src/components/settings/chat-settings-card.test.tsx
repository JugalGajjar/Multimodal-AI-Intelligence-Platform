import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatSettingsCard } from "./chat-settings-card";
import { useAuthStore } from "@/store/auth";

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

function ok(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("<ChatSettingsCard />", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    useAuthStore.getState().setSession({ id: "u-1", email: "a@b.com" }, "tok");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.getState().clearSession();
  });

  it("loads settings and marks the active mode", async () => {
    fetchMock.mockResolvedValueOnce(ok({ rag_mode: "strict", web_max_results: 5 }));

    renderWithQuery(<ChatSettingsCard />);

    await waitFor(() => {
      expect(screen.getByTestId("rag-mode-strict")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(screen.getByTestId("rag-mode-regular")).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByTestId("web-max-results-value")).toHaveTextContent("5");
  });

  it("PATCHes rag_mode when the inactive mode is clicked", async () => {
    fetchMock
      .mockResolvedValueOnce(ok({ rag_mode: "strict", web_max_results: 5 }))
      .mockResolvedValueOnce(ok({ rag_mode: "regular", web_max_results: 5 }))
      .mockResolvedValueOnce(ok({ rag_mode: "regular", web_max_results: 5 }));

    renderWithQuery(<ChatSettingsCard />);
    await screen.findByTestId("rag-mode-regular");

    await userEvent.click(screen.getByTestId("rag-mode-regular"));

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCall).toBeDefined();
      expect(JSON.parse((patchCall![1] as RequestInit).body as string)).toEqual(
        { rag_mode: "regular" },
      );
    });
  });

  it("does not PATCH when the already-active mode is clicked", async () => {
    fetchMock.mockResolvedValueOnce(ok({ rag_mode: "strict", web_max_results: 5 }));

    renderWithQuery(<ChatSettingsCard />);
    await screen.findByTestId("rag-mode-strict");

    await userEvent.click(screen.getByTestId("rag-mode-strict"));

    const patchCalls = fetchMock.mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
    );
    expect(patchCalls).toHaveLength(0);
  });

  it("commits the slider via PATCH on release", async () => {
    fetchMock
      .mockResolvedValueOnce(ok({ rag_mode: "strict", web_max_results: 5 }))
      .mockResolvedValueOnce(ok({ rag_mode: "strict", web_max_results: 8 }))
      .mockResolvedValueOnce(ok({ rag_mode: "strict", web_max_results: 8 }));

    renderWithQuery(<ChatSettingsCard />);
    const slider = await screen.findByLabelText(/max websites/i);

    // fireEvent-style change then blur to trigger the commit path.
    const { fireEvent } = await import("@testing-library/react");
    fireEvent.change(slider, { target: { value: "8" } });
    fireEvent.blur(slider);

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCall).toBeDefined();
      expect(JSON.parse((patchCall![1] as RequestInit).body as string)).toEqual(
        { web_max_results: 8 },
      );
    });
  });
});
