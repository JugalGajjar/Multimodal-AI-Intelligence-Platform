import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The transcript reuses <Answer>, which mounts the canvas-heavy graph.
vi.mock("@/components/graph/knowledge-graph", () => ({
  KnowledgeGraph: () => <div data-testid="kg-stub" />,
}));

import { ChatsList } from "./chats-list";
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

const CHAT = {
  id: "11111111-1111-1111-1111-111111111111",
  title: "Prompt engineering basics",
  summary: "User asked about prompting techniques.",
  message_count: 4,
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
};

const DETAIL = {
  ...CHAT,
  messages: [
    {
      id: "m1",
      seq: 0,
      role: "user",
      content: "What is prompt engineering?",
      created_at: "2026-06-12T00:00:00Z",
      citations: [],
      web_citations: [],
      verification: null,
      response_meta: null,
    },
    {
      id: "m2",
      seq: 1,
      role: "assistant",
      content: "It is **instruction design** for AI models.",
      created_at: "2026-06-12T00:00:01Z",
      citations: [],
      web_citations: [],
      verification: null,
      response_meta: { model: "m", used_context: true },
    },
  ],
};

describe("<ChatsList />", () => {
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

  it("renders the list with title, summary, and count", async () => {
    fetchMock.mockResolvedValueOnce(ok({ items: [CHAT], total: 1 }));

    renderWithQuery(<ChatsList />);

    expect(await screen.findByTestId("chat-title")).toHaveTextContent(
      "Prompt engineering basics",
    );
    expect(screen.getByText(/4 messages/i)).toBeInTheDocument();
    expect(
      screen.getByText(/asked about prompting techniques/i),
    ).toBeInTheDocument();
  });

  it("debounced search hits the search endpoint and shows the snippet", async () => {
    fetchMock
      .mockResolvedValueOnce(ok({ items: [CHAT], total: 1 }))
      .mockResolvedValueOnce(
        ok({
          items: [
            { ...CHAT, snippet: "…the zebra codeword…", match_source: "message" },
          ],
          total: 1,
          query: "zebra",
        }),
      );

    renderWithQuery(<ChatsList />);
    await screen.findByTestId("chat-title");

    await userEvent.type(screen.getByTestId("chats-search"), "zebra");

    await waitFor(() => {
      const searchCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/chats/search?q=zebra"),
      );
      expect(searchCall).toBeDefined();
    });
    expect(await screen.findByTestId("chat-snippet")).toHaveTextContent(
      /zebra codeword/i,
    );
    expect(screen.getByText(/matched message/i)).toBeInTheDocument();
  });

  it("inline rename PATCHes on Enter", async () => {
    fetchMock
      .mockResolvedValueOnce(ok({ items: [CHAT], total: 1 }))
      .mockResolvedValueOnce(ok({ ...CHAT, title: "Renamed!" }))
      .mockResolvedValueOnce(ok({ items: [{ ...CHAT, title: "Renamed!" }], total: 1 }));

    renderWithQuery(<ChatsList />);
    await screen.findByTestId("chat-title");

    await userEvent.click(screen.getByTestId("chat-rename-button"));
    const input = screen.getByTestId("chat-rename-input");
    await userEvent.clear(input);
    await userEvent.type(input, "Renamed!{Enter}");

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
      );
      expect(patchCall).toBeDefined();
      expect(JSON.parse((patchCall![1] as RequestInit).body as string)).toEqual(
        { title: "Renamed!" },
      );
    });
  });

  it("escape cancels rename without a PATCH", async () => {
    fetchMock.mockResolvedValueOnce(ok({ items: [CHAT], total: 1 }));

    renderWithQuery(<ChatsList />);
    await screen.findByTestId("chat-title");

    await userEvent.click(screen.getByTestId("chat-rename-button"));
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByTestId("chat-rename-input")).not.toBeInTheDocument();
    const patchCalls = fetchMock.mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
    );
    expect(patchCalls).toHaveLength(0);
  });

  it("delete calls DELETE and refreshes", async () => {
    fetchMock
      .mockResolvedValueOnce(ok({ items: [CHAT], total: 1 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(ok({ items: [], total: 0 }));

    renderWithQuery(<ChatsList />);
    await screen.findByTestId("chat-title");

    await userEvent.click(screen.getByTestId("chat-delete-button"));

    await waitFor(() => {
      const deleteCall = fetchMock.mock.calls.find(
        (c) => (c[1] as RequestInit | undefined)?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
    });
  });

  it("expanding shows a read-only markdown transcript with no input", async () => {
    fetchMock
      .mockResolvedValueOnce(ok({ items: [CHAT], total: 1 }))
      .mockResolvedValueOnce(ok(DETAIL));

    renderWithQuery(<ChatsList />);
    await screen.findByTestId("chat-title");

    await userEvent.click(screen.getByRole("button", { name: /transcript/i }));

    const transcript = await screen.findByTestId("chat-transcript");
    expect(
      within(transcript).getByText(/what is prompt engineering\?/i),
    ).toBeInTheDocument();
    // Assistant markdown rendered.
    const strong = transcript.querySelector("strong");
    expect(strong).not.toBeNull();
    expect(strong!.textContent).toBe("instruction design");
    // Read-only: no textarea/input inside the transcript.
    expect(transcript.querySelector("textarea")).toBeNull();
    expect(transcript.querySelector("input")).toBeNull();
  });
});
