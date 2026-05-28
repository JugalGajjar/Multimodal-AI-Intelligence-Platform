import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPanel } from "./chat-panel";
import { useAuthStore } from "@/store/auth";

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const SUCCESS_BODY = {
  answer:
    "Embeddings use 384 dimensions [1] and chunks are about 500 chars [2].",
  citations: [
    {
      chunk_id: "11111111-1111-1111-1111-111111111111",
      document_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      chunk_index: 0,
      score: 0.812,
      text_preview: "First chunk preview",
    },
    {
      chunk_id: "22222222-2222-2222-2222-222222222222",
      document_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      chunk_index: 1,
      score: 0.701,
      text_preview: "Second chunk preview",
    },
  ],
  model: "openai/gpt-oss-20b:free",
  used_context: true,
};

describe("<ChatPanel />", () => {
  beforeEach(() => {
    useAuthStore.getState().setSession(
      { id: "u-1", email: "a@b.com" },
      "tok-abc",
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.getState().clearSession();
  });

  it("submit is disabled when input is empty", async () => {
    vi.stubGlobal("fetch", vi.fn());
    renderWithQuery(<ChatPanel />);

    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
  });

  it("posting a question shows loading then renders answer + citations", async () => {
    // Deferred so the test can observe the in-flight loading state.
    let resolveFetch!: (r: Response) => void;
    const deferred = new Promise<Response>((r) => {
      resolveFetch = r;
    });
    const fetchMock = vi.fn().mockReturnValue(deferred);
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<ChatPanel />);

    await userEvent.type(
      screen.getByLabelText(/question/i),
      "What is the embedding dim?",
    );
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    // While the fetch is still pending, the button shows the loading label.
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /thinking/i }),
      ).toBeInTheDocument();
    });

    // Resolve the fetch — the answer should now render.
    resolveFetch(jsonResponse(SUCCESS_BODY));

    await waitFor(() => {
      expect(screen.getByTestId("chat-answer")).toBeInTheDocument();
    });

    // Answer text rendered
    expect(
      screen.getByText(/embeddings use 384 dimensions/i),
    ).toBeInTheDocument();

    // Model + used-context badges
    expect(screen.getByText("openai/gpt-oss-20b:free")).toBeInTheDocument();
    expect(screen.getByText(/used context/i)).toBeInTheDocument();

    // 2 citations rendered
    const items = screen.getAllByTestId("citation-item");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText(/first chunk preview/i)).toBeInTheDocument();
    expect(within(items[0]).getByText(/score 0\.812/)).toBeInTheDocument();
    expect(within(items[1]).getByText(/second chunk preview/i)).toBeInTheDocument();

    // POST went to /chat with Bearer
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/chat$/);
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok-abc",
    });
  });

  it("shows a 'no context' badge when used_context is false", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          answer: "I have no documents to answer from.",
          citations: [],
          model: "m",
          used_context: false,
        }),
      ),
    );

    renderWithQuery(<ChatPanel />);
    await userEvent.type(screen.getByLabelText(/question/i), "anything");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() => {
      expect(screen.getByTestId("chat-answer")).toBeInTheDocument();
    });
    expect(screen.getByText(/no context/i)).toBeInTheDocument();
    expect(screen.queryByTestId("citation-item")).not.toBeInTheDocument();
  });

  it("renders a friendly 429 rate-limit message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "rate limited" }), {
          status: 429,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    renderWithQuery(<ChatPanel />);
    await userEvent.type(screen.getByLabelText(/question/i), "anything");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /rate limit/i,
    );
  });

  it("renders a friendly 503 missing-key message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "no key" }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    renderWithQuery(<ChatPanel />);
    await userEvent.type(screen.getByLabelText(/question/i), "anything");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /not configured|openrouter/i,
    );
  });

  it("trims whitespace before submitting and won't submit blanks", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<ChatPanel />);
    const input = screen.getByLabelText(/question/i);
    await userEvent.type(input, "   ");
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
