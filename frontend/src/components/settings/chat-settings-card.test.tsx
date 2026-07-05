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

const MODELS_RESPONSE = {
  default: "openai/gpt-oss-120b",
  models: [
    {
      id: "openai/gpt-oss-120b",
      label: "GPT-OSS 120B",
      provider: "Groq",
      category: "open-source",
      notes: "Larger, stronger reasoning.",
      is_default: true,
    },
    {
      id: "qwen/qwen3-32b",
      label: "Qwen3 32B",
      provider: "Groq",
      category: "open-source",
      notes: "Alternative family.",
      is_default: false,
    },
  ],
};

describe("<ChatSettingsCard />", () => {
  const fetchMock = vi.fn();
  // Per-test FIFO queue for /auth/settings responses only — the /chat/models
  // endpoint fires concurrently, so we can't share one mock chain across both.
  const settingsResponses: Response[] = [];
  function queueSettings(...responses: Response[]) {
    settingsResponses.push(...responses);
  }

  beforeEach(() => {
    fetchMock.mockReset();
    settingsResponses.length = 0;
    fetchMock.mockImplementation((url: string | URL) => {
      const u = String(url);
      if (u.includes("/chat/models")) return Promise.resolve(ok(MODELS_RESPONSE));
      if (u.includes("/auth/settings")) {
        const next = settingsResponses.shift();
        if (!next) return Promise.reject(new Error("no queued settings response"));
        return Promise.resolve(next);
      }
      return Promise.reject(new Error("unhandled fetch: " + u));
    });
    vi.stubGlobal("fetch", fetchMock);
    useAuthStore.getState().setSession({ id: "u-1", email: "a@b.com" }, "tok");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.getState().clearSession();
  });

  it("loads settings and marks the active mode", async () => {
    queueSettings(ok({ rag_mode: "strict", web_max_results: 5, chat_model: null }));

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
    queueSettings(
      ok({ rag_mode: "strict", web_max_results: 5, chat_model: null }),
      ok({ rag_mode: "regular", web_max_results: 5, chat_model: null }),
      ok({ rag_mode: "regular", web_max_results: 5, chat_model: null }),
    );

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
    queueSettings(ok({ rag_mode: "strict", web_max_results: 5, chat_model: null }));

    renderWithQuery(<ChatSettingsCard />);
    await screen.findByTestId("rag-mode-strict");

    await userEvent.click(screen.getByTestId("rag-mode-strict"));

    const patchCalls = fetchMock.mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
    );
    expect(patchCalls).toHaveLength(0);
  });

  it("commits the slider via PATCH on release", async () => {
    queueSettings(
      ok({ rag_mode: "strict", web_max_results: 5, chat_model: null }),
      ok({ rag_mode: "strict", web_max_results: 8, chat_model: null }),
      ok({ rag_mode: "strict", web_max_results: 8, chat_model: null }),
    );

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

  it("renders the model picker with the curated list + a Default option", async () => {
    queueSettings(ok({ rag_mode: "strict", web_max_results: 5, chat_model: null }));

    renderWithQuery(<ChatSettingsCard />);
    const select = (await screen.findByTestId(
      "chat-model-select",
    )) as HTMLSelectElement;

    const optionTexts = Array.from(select.options).map((o) => o.textContent);
    expect(optionTexts.some((t) => t?.startsWith("Default"))).toBe(true);
    expect(optionTexts.some((t) => t?.includes("GPT-OSS 120B"))).toBe(true);
    expect(optionTexts.some((t) => t?.includes("Qwen3 32B"))).toBe(true);
    // Empty string = follow the server default.
    expect(select.value).toBe("");
  });

  it("PATCHes chat_model when the user picks a specific model", async () => {
    queueSettings(
      ok({ rag_mode: "strict", web_max_results: 5, chat_model: null }),
      ok({
        rag_mode: "strict",
        web_max_results: 5,
        chat_model: "qwen/qwen3-32b",
      }),
      ok({
        rag_mode: "strict",
        web_max_results: 5,
        chat_model: "qwen/qwen3-32b",
      }),
    );

    renderWithQuery(<ChatSettingsCard />);
    const select = await screen.findByTestId("chat-model-select");

    await userEvent.selectOptions(select, "qwen/qwen3-32b");

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCall).toBeDefined();
      expect(
        JSON.parse((patchCall![1] as RequestInit).body as string),
      ).toEqual({ chat_model: "qwen/qwen3-32b" });
    });
  });

  it("PATCHes chat_model: null when the user picks Default", async () => {
    queueSettings(
      ok({
        rag_mode: "strict",
        web_max_results: 5,
        chat_model: "qwen/qwen3-32b",
      }),
      ok({ rag_mode: "strict", web_max_results: 5, chat_model: null }),
      ok({ rag_mode: "strict", web_max_results: 5, chat_model: null }),
    );

    renderWithQuery(<ChatSettingsCard />);
    const select = (await screen.findByTestId(
      "chat-model-select",
    )) as HTMLSelectElement;
    // Start with an override — the dropdown reflects it.
    await waitFor(() => expect(select.value).toBe("qwen/qwen3-32b"));

    await userEvent.selectOptions(select, "");

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCall).toBeDefined();
      expect(
        JSON.parse((patchCall![1] as RequestInit).body as string),
      ).toEqual({ chat_model: null });
    });
  });
});
