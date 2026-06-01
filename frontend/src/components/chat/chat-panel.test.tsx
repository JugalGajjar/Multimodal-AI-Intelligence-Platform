import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Stub the (canvas-heavy) graph component so this suite can focus on the
// chat-panel logic. The real <KnowledgeGraph /> is exercised in its own tests.
vi.mock("@/components/graph/knowledge-graph", () => ({
  KnowledgeGraph: (props: {
    nodes: { id: string }[];
    highlighted?: ReadonlySet<string>;
  }) => (
    <div
      data-testid="kg-stub"
      data-node-count={props.nodes.length}
      data-highlight-count={props.highlighted?.size ?? 0}
    />
  ),
}));

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

  describe("inline knowledge graph", () => {
    const GRAPH_BODY = {
      answer: "Qdrant powers retrieval and Cosine Distance is the metric.",
      citations: [],
      entities_used: [
        {
          name: "Qdrant",
          type: "Technology",
          description: "vector DB",
          relations: [
            {
              relation: "uses",
              direction: "out" as const,
              other: "Cosine Distance",
              other_type: "Concept",
              other_description: "similarity metric",
            },
          ],
        },
        {
          name: "Cosine Distance",
          type: "Concept",
          description: "similarity metric",
          relations: [],
        },
      ],
      model: "openai/gpt-oss-20b",
      used_context: false,
      used_graph: true,
    };

    it("renders the inline graph + 'used graph' badge when used_graph=true", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(jsonResponse(GRAPH_BODY)),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      await waitFor(() =>
        expect(screen.getByTestId("inline-graph")).toBeInTheDocument(),
      );

      // Used-graph badge appears
      expect(screen.getByText(/used graph/i)).toBeInTheDocument();

      // Graph stub received 2 nodes (both primary entities)
      const stub = screen.getByTestId("kg-stub");
      expect(stub.getAttribute("data-node-count")).toBe("2");
      // Both entity names appear in the answer ⇒ both highlighted
      expect(stub.getAttribute("data-highlight-count")).toBe("2");
    });

    it("hides the inline graph when used_graph=false", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          jsonResponse({
            ...GRAPH_BODY,
            used_graph: false,
            entities_used: [],
          }),
        ),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      await waitFor(() =>
        expect(screen.getByTestId("chat-answer")).toBeInTheDocument(),
      );
      expect(screen.queryByTestId("inline-graph")).not.toBeInTheDocument();
      expect(screen.queryByText(/used graph/i)).not.toBeInTheDocument();
    });

    it("'Explore full graph' link points at /dashboard/graph", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(jsonResponse(GRAPH_BODY)),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      const link = await screen.findByTestId("inline-graph-explore-link");
      expect(link).toHaveAttribute("href", "/dashboard/graph");
    });
  });

  describe("verification badge (Phase 5.2)", () => {
    function verifiedBody(verdict: "verified" | "partial" | "unsupported", extras: object = {}) {
      return {
        answer: "Some answer.",
        citations: [],
        entities_used: [],
        model: "openai/gpt-oss-20b",
        used_context: true,
        used_graph: false,
        verification: {
          verdict,
          groundedness_score: verdict === "verified" ? 1 : verdict === "partial" ? 0.5 : 0.1,
          total_claims: 2,
          supported_claims: verdict === "verified" ? 2 : 1,
          unsupported_claims: verdict === "verified" ? [] : ["fabricated bit"],
          skip_reason: "",
          ...extras,
        },
      };
    }

    function skippedBody(reason: string) {
      return {
        answer: "x",
        citations: [],
        entities_used: [],
        model: "openai/gpt-oss-20b",
        used_context: false,
        used_graph: false,
        verification: {
          verdict: "skipped",
          groundedness_score: 0,
          total_claims: 0,
          supported_claims: 0,
          unsupported_claims: [],
          skip_reason: reason,
        },
      };
    }

    it("renders a green verified badge on full groundedness", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(jsonResponse(verifiedBody("verified"))),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      const badge = await screen.findByTestId("verification-badge");
      expect(badge).toHaveTextContent(/verified/i);
      expect(badge).toHaveTextContent(/100%/);
    });

    it("renders an amber partial badge with the unsupported-claims panel collapsed by default", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(jsonResponse(verifiedBody("partial"))),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      const badge = await screen.findByTestId("verification-badge");
      expect(badge).toHaveTextContent(/partial/i);
      // Panel exists but claims list is hidden until expanded.
      const panel = screen.getByTestId("unsupported-claims-panel");
      expect(panel).toBeInTheDocument();
      expect(
        screen.queryByTestId("unsupported-claims-list"),
      ).not.toBeInTheDocument();
    });

    it("expanding the panel reveals each unsupported claim", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          jsonResponse(
            verifiedBody("unsupported", {
              unsupported_claims: ["first bad claim", "second bad claim"],
            }),
          ),
        ),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      await screen.findByTestId("verification-badge");
      await userEvent.click(
        screen.getByRole("button", { name: /unsupported claim/i }),
      );

      const list = screen.getByTestId("unsupported-claims-list");
      expect(within(list).getByText("first bad claim")).toBeInTheDocument();
      expect(within(list).getByText("second bad claim")).toBeInTheDocument();
    });

    it("renders a muted 'not verified' badge and no panel when the verdict is skipped", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(jsonResponse(skippedBody("no context to verify against"))),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      const badge = await screen.findByTestId("verification-badge");
      expect(badge).toHaveTextContent(/not verified/i);
      expect(
        screen.queryByTestId("unsupported-claims-panel"),
      ).not.toBeInTheDocument();
    });
  });
});
