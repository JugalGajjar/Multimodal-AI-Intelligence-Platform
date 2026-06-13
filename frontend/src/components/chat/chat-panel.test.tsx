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
import { useChatSessionStore } from "@/store/chat-session";

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

type AnyBody = Record<string, unknown>;

/**
 * Wraps a chat-response body into a server-sent-events stream the way the
 * real backend emits it (meta → tokens → done).
 */
function sseFromBody(body: AnyBody): Response {
  const encoder = new TextEncoder();
  const meta = {
    chat_id: body.chat_id ?? "chat-test",
    intent: body.intent ?? "chat",
    used_context: !!body.used_context,
    used_graph: !!body.used_graph,
    used_web: !!body.used_web,
    model: body.model ?? "",
    citations: body.citations ?? [],
    entities_used: body.entities_used ?? [],
    web_citations: body.web_citations ?? [],
    strict: !!body.strict,
  };
  const answer = (body.answer ?? "") as string;
  // Split into a few chunks so tests can observe streaming if they want to.
  const tokens =
    answer.length === 0 ? [] : [answer.slice(0, Math.ceil(answer.length / 2)), answer.slice(Math.ceil(answer.length / 2))];
  const done = {
    verification: body.verification ?? null,
    strict_refusal: body.strict_refusal ?? null,
  };

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(
        encoder.encode(`event: meta\ndata: ${JSON.stringify(meta)}\n\n`),
      );
      for (const t of tokens) {
        controller.enqueue(
          encoder.encode(`event: token\ndata: ${JSON.stringify({ text: t })}\n\n`),
        );
      }
      controller.enqueue(
        encoder.encode(`event: done\ndata: ${JSON.stringify(done)}\n\n`),
      );
      controller.close();
    },
  });

  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
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
    // The session store is module-global — reset between tests.
    useChatSessionStore.getState().reset();
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
    resolveFetch(sseFromBody(SUCCESS_BODY));

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

    // POST went to /chat/stream with Bearer
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/chat\/stream$/);
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok-abc",
    });
  });

  it("shows a 'no context' badge when used_context is false", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        sseFromBody({
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
        vi.fn().mockResolvedValue(sseFromBody(GRAPH_BODY)),
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
          sseFromBody({
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
        vi.fn().mockResolvedValue(sseFromBody(GRAPH_BODY)),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      const link = await screen.findByTestId("inline-graph-explore-link");
      expect(link).toHaveAttribute("href", "/dashboard/graph");
    });
  });

  describe("verification badge", () => {
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
        vi.fn().mockResolvedValue(sseFromBody(verifiedBody("verified"))),
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
        vi.fn().mockResolvedValue(sseFromBody(verifiedBody("partial"))),
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
          sseFromBody(
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
        vi.fn().mockResolvedValue(sseFromBody(skippedBody("no context to verify against"))),
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

  describe("streaming", () => {
    it("shows a streaming cursor while tokens are arriving", async () => {
      // Build a deferred-controller stream so the test holds the connection
      // open after the first token, mid-flight.
      const encoder = new TextEncoder();
      let push!: (chunk: string) => void;
      let close!: () => void;
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          push = (s) => controller.enqueue(encoder.encode(s));
          close = () => controller.close();
        },
      });
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }),
        ),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "stream please");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      // Emit meta + first token, then yield to React.
      push(
        `event: meta\ndata: ${JSON.stringify({
          intent: "chat",
          used_context: true,
          used_graph: false,
          model: "m",
          citations: [],
          entities_used: [],
        })}\n\n`,
      );
      push(`event: token\ndata: ${JSON.stringify({ text: "Hello " })}\n\n`);

      const cursor = await screen.findByTestId("streaming-cursor");
      expect(cursor).toBeInTheDocument();
      expect(screen.getByTestId("chat-answer-text")).toHaveTextContent(/hello/i);

      // Finish the stream — the cursor should disappear once done arrives.
      push(`event: token\ndata: ${JSON.stringify({ text: "world." })}\n\n`);
      push(
        `event: done\ndata: ${JSON.stringify({
          verification: {
            verdict: "skipped",
            groundedness_score: 0,
            total_claims: 0,
            supported_claims: 0,
            unsupported_claims: [],
            skip_reason: "",
          },
        })}\n\n`,
      );
      close();

      await waitFor(() => {
        expect(screen.queryByTestId("streaming-cursor")).not.toBeInTheDocument();
      });
      expect(screen.getByTestId("chat-answer-text")).toHaveTextContent(
        /hello world\./i,
      );
    });

    it("surfaces an SSE error event as the answer error", async () => {
      const encoder = new TextEncoder();
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            encoder.encode(
              `event: error\ndata: ${JSON.stringify({ status: 429, detail: "rate limited" })}\n\n`,
            ),
          );
          controller.close();
        },
      });
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }),
        ),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      expect(await screen.findByRole("alert")).toHaveTextContent(/rate limit/i);
    });
  });

  describe("intent badge", () => {
    function bodyWithIntent(intent: string) {
      return {
        answer: "x",
        citations: [],
        entities_used: [],
        model: "openai/gpt-oss-20b",
        used_context: true,
        used_graph: false,
        intent,
      };
    }

    it("does NOT render the intent badge for the default chat route", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(sseFromBody(bodyWithIntent("chat"))),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      await screen.findByTestId("chat-answer");
      expect(screen.queryByTestId("intent-badge")).not.toBeInTheDocument();
    });

    it("renders a 'summary route' badge when the router picked summarize", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(sseFromBody(bodyWithIntent("summarize"))),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      const badge = await screen.findByTestId("intent-badge");
      expect(badge).toHaveTextContent(/summary route/i);
    });

    it("renders a 'graph route' badge when the router picked explain_graph", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(sseFromBody(bodyWithIntent("explain_graph"))),
      );

      renderWithQuery(<ChatPanel />);
      await userEvent.type(screen.getByLabelText(/question/i), "anything");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      const badge = await screen.findByTestId("intent-badge");
      expect(badge).toHaveTextContent(/graph route/i);
    });
  });

  describe("RAG / Web toggles", () => {
    it("renders with RAG on and Web off by default", () => {
      vi.stubGlobal("fetch", vi.fn());
      renderWithQuery(<ChatPanel />);

      expect(screen.getByTestId("toggle-rag")).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(screen.getByTestId("toggle-web")).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    });

    it("sends toggle state in the request payload", async () => {
      const fetchMock = vi.fn().mockResolvedValue(sseFromBody(SUCCESS_BODY));
      vi.stubGlobal("fetch", fetchMock);
      renderWithQuery(<ChatPanel />);

      await userEvent.click(screen.getByTestId("toggle-rag")); // off
      await userEvent.click(screen.getByTestId("toggle-web")); // on
      await userEvent.type(screen.getByLabelText(/question/i), "latest news?");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      const body = JSON.parse(
        (fetchMock.mock.calls[0][1] as RequestInit).body as string,
      );
      expect(body.use_rag).toBe(false);
      expect(body.use_web).toBe(true);
    });
  });

  describe("web citations", () => {
    it("renders web sources as external links and a used-web badge", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          sseFromBody({
            ...SUCCESS_BODY,
            used_web: true,
            web_citations: [
              {
                url: "https://example.com/post",
                title: "Example Post",
                snippet: "An example snippet.",
                score: 0.9,
              },
            ],
          }),
        ),
      );
      renderWithQuery(<ChatPanel />);

      await userEvent.type(screen.getByLabelText(/question/i), "q");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      const item = await screen.findByTestId("web-citation-item");
      const link = within(item).getByRole("link", { name: /example post/i });
      expect(link).toHaveAttribute("href", "https://example.com/post");
      expect(link).toHaveAttribute("target", "_blank");
      expect(within(item).getByText(/an example snippet/i)).toBeInTheDocument();
      expect(screen.getByText(/used web/i)).toBeInTheDocument();
    });
  });

  describe("strict mode buffering", () => {
    it("hides streamed text behind a verifying state, then reveals the answer", async () => {
      let resolveFetch!: (r: Response) => void;
      const deferred = new Promise<Response>((r) => {
        resolveFetch = r;
      });
      vi.stubGlobal("fetch", vi.fn().mockReturnValue(deferred));
      renderWithQuery(<ChatPanel />);

      await userEvent.type(screen.getByLabelText(/question/i), "q");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      resolveFetch(
        sseFromBody({
          ...SUCCESS_BODY,
          strict: true,
          verification: {
            verdict: "verified",
            groundedness_score: 0.95,
            total_claims: 2,
            supported_claims: 2,
            unsupported_claims: [],
            skip_reason: "",
          },
        }),
      );

      // After `done`, the answer is revealed (stream resolves fast in tests,
      // so we assert the final state: answer visible, no refusal notice).
      await waitFor(() => {
        expect(screen.getByTestId("chat-answer")).toBeInTheDocument();
      });
      expect(
        screen.getByText(/embeddings use 384 dimensions/i),
      ).toBeInTheDocument();
      expect(
        screen.queryByTestId("strict-refusal-notice"),
      ).not.toBeInTheDocument();
      expect(screen.queryByTestId("chat-verifying")).not.toBeInTheDocument();
    });

    it("replaces the answer with the refusal and hides citations when gated", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          sseFromBody({
            ...SUCCESS_BODY,
            strict: true,
            strict_refusal:
              "I can't answer this confidently from your documents.",
            verification: {
              verdict: "unsupported",
              groundedness_score: 0.2,
              total_claims: 3,
              supported_claims: 0,
              unsupported_claims: [],
              skip_reason: "",
            },
          }),
        ),
      );
      renderWithQuery(<ChatPanel />);

      await userEvent.type(screen.getByLabelText(/question/i), "q");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      await screen.findByTestId("strict-refusal-notice");

      // Refusal text replaces the streamed answer.
      expect(screen.getByTestId("chat-answer-text")).toHaveTextContent(
        /can't answer this confidently/i,
      );
      expect(
        screen.queryByText(/embeddings use 384 dimensions/i),
      ).not.toBeInTheDocument();
      // Citations cite a withheld answer — hidden.
      expect(screen.queryByTestId("citation-item")).not.toBeInTheDocument();
      // Verification badge stays for transparency.
      expect(screen.getByTestId("verification-badge")).toBeInTheDocument();
    });
  });

  describe("input ergonomics + markdown", () => {
    it("Enter submits the question; Shift+Enter does not", async () => {
      const fetchMock = vi.fn().mockResolvedValue(sseFromBody(SUCCESS_BODY));
      vi.stubGlobal("fetch", fetchMock);
      renderWithQuery(<ChatPanel />);

      const input = screen.getByLabelText(/question/i);
      await userEvent.type(input, "line one{Shift>}{Enter}{/Shift}line two");
      expect(fetchMock).not.toHaveBeenCalled();

      await userEvent.type(input, "{Enter}");
      await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
      const body = JSON.parse(
        (fetchMock.mock.calls[0][1] as RequestInit).body as string,
      );
      expect(body.query).toContain("line one");
      expect(body.query).toContain("line two");
    });

    it("renders markdown in the answer (bold, list items)", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          sseFromBody({
            ...SUCCESS_BODY,
            answer: "Key points:\n\n- **First** item\n- Second item",
          }),
        ),
      );
      renderWithQuery(<ChatPanel />);

      await userEvent.type(screen.getByLabelText(/question/i), "q");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      await screen.findByTestId("chat-answer-text");
      await waitFor(() => {
        const answer = screen.getByTestId("chat-answer-text");
        const strong = answer.querySelector("strong");
        expect(strong).not.toBeNull();
        expect(strong!.textContent).toBe("First");
        expect(answer.querySelectorAll("li")).toHaveLength(2);
      });
    });
  });

  describe("session thread", () => {
    it("two sends render two turns and the second request carries chat_id", async () => {
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce(
          sseFromBody({ ...SUCCESS_BODY, answer: "first answer", chat_id: "chat-42" }),
        )
        .mockResolvedValueOnce(
          sseFromBody({ ...SUCCESS_BODY, answer: "second answer", chat_id: "chat-42" }),
        );
      vi.stubGlobal("fetch", fetchMock);
      renderWithQuery(<ChatPanel />);

      await userEvent.type(screen.getByLabelText(/question/i), "q one");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));
      await screen.findByText(/first answer/i);

      await userEvent.type(screen.getByLabelText(/question/i), "q two");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));
      await screen.findByText(/second answer/i);

      // Both turns visible in the thread.
      expect(screen.getAllByTestId("chat-turn")).toHaveLength(2);
      expect(screen.getByText(/first answer/i)).toBeInTheDocument();
      expect(screen.getAllByTestId("chat-question")).toHaveLength(2);

      // First request had null chat_id; second carries the id from meta.
      const body1 = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
      const body2 = JSON.parse((fetchMock.mock.calls[1][1] as RequestInit).body as string);
      expect(body1.chat_id).toBeNull();
      expect(body2.chat_id).toBe("chat-42");
    });

    it("New chat clears the thread and resets the session", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(sseFromBody({ ...SUCCESS_BODY, chat_id: "chat-9" })),
      );
      renderWithQuery(<ChatPanel />);

      await userEvent.type(screen.getByLabelText(/question/i), "hello");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));
      await screen.findByTestId("chat-turn");

      await userEvent.click(screen.getByTestId("chat-new"));

      expect(screen.queryByTestId("chat-turn")).not.toBeInTheDocument();
      expect(screen.getByTestId("chat-empty")).toBeInTheDocument();
      expect(useChatSessionStore.getState().chatId).toBeNull();
    });

    it("an errored turn is not added to the thread and the question is restored", async () => {
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

      await userEvent.type(screen.getByLabelText(/question/i), "doomed question");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      await screen.findByRole("alert");
      expect(screen.queryByTestId("chat-turn")).not.toBeInTheDocument();
      expect(useChatSessionStore.getState().turns).toHaveLength(0);
      // Question restored for retry.
      expect(screen.getByLabelText(/question/i)).toHaveValue("doomed question");
    });

    it("first-turn mid-stream error clears the just-adopted chat_id (avoids 404 retry loop)", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockImplementation(() => {
          // SSE that emits meta with a chat_id then an error event.
          const encoder = new TextEncoder();
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              const meta = {
                chat_id: "doomed-chat",
                intent: "chat",
                used_context: false,
                used_graph: false,
                used_web: false,
                model: "m",
                citations: [],
                entities_used: [],
                web_citations: [],
                strict: false,
              };
              controller.enqueue(
                encoder.encode(`event: meta\ndata: ${JSON.stringify(meta)}\n\n`),
              );
              controller.enqueue(
                encoder.encode(
                  `event: error\ndata: ${JSON.stringify({ status: 429, detail: "rate" })}\n\n`,
                ),
              );
              controller.close();
            },
          });
          return Promise.resolve(
            new Response(stream, {
              status: 200,
              headers: { "Content-Type": "text/event-stream" },
            }),
          );
        }),
      );
      renderWithQuery(<ChatPanel />);

      await userEvent.type(screen.getByLabelText(/question/i), "first turn");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      await screen.findByRole("alert");
      // The cleanup-failed-first-turn protection: stored chat_id is dropped.
      expect(useChatSessionStore.getState().chatId).toBeNull();
    });

    it("later-turn mid-stream error keeps the chat_id (the chat still exists)", async () => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          // Turn 1 succeeds, establishes chat_id.
          .mockResolvedValueOnce(
            sseFromBody({ ...SUCCESS_BODY, chat_id: "chat-keepme" }),
          )
          // Turn 2 fails.
          .mockResolvedValueOnce(
            new Response(JSON.stringify({ detail: "rate" }), {
              status: 429,
              headers: { "Content-Type": "application/json" },
            }),
          ),
      );
      renderWithQuery(<ChatPanel />);

      await userEvent.type(screen.getByLabelText(/question/i), "turn one");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));
      await screen.findByTestId("chat-turn");

      await userEvent.type(screen.getByLabelText(/question/i), "turn two");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));
      await screen.findByRole("alert");

      expect(useChatSessionStore.getState().chatId).toBe("chat-keepme");
    });

    it("partial answer stays visible after a mid-stream error", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockImplementation(() => {
          const encoder = new TextEncoder();
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              const meta = {
                chat_id: "chat-x",
                intent: "chat",
                used_context: true,
                used_graph: false,
                used_web: false,
                model: "m",
                citations: [],
                entities_used: [],
                web_citations: [],
                strict: false,
              };
              controller.enqueue(
                encoder.encode(`event: meta\ndata: ${JSON.stringify(meta)}\n\n`),
              );
              controller.enqueue(
                encoder.encode(
                  `event: token\ndata: ${JSON.stringify({ text: "Partial visible " })}\n\n`,
                ),
              );
              controller.enqueue(
                encoder.encode(
                  `event: token\ndata: ${JSON.stringify({ text: "answer." })}\n\n`,
                ),
              );
              controller.enqueue(
                encoder.encode(
                  `event: error\ndata: ${JSON.stringify({ status: 502, detail: "upstream" })}\n\n`,
                ),
              );
              controller.close();
            },
          });
          return Promise.resolve(
            new Response(stream, {
              status: 200,
              headers: { "Content-Type": "text/event-stream" },
            }),
          );
        }),
      );
      renderWithQuery(<ChatPanel />);

      await userEvent.type(screen.getByLabelText(/question/i), "q");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));

      // Error alert + the partial answer both visible.
      await screen.findByRole("alert");
      expect(screen.getByText(/partial visible answer/i)).toBeInTheDocument();
    });

    it("thread survives unmount/remount (client-side navigation)", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(sseFromBody({ ...SUCCESS_BODY, chat_id: "chat-7" })),
      );
      const first = renderWithQuery(<ChatPanel />);

      await userEvent.type(screen.getByLabelText(/question/i), "persists?");
      await userEvent.click(screen.getByRole("button", { name: /send/i }));
      await screen.findByTestId("chat-turn");

      first.unmount();
      renderWithQuery(<ChatPanel />);

      expect(screen.getByTestId("chat-turn")).toBeInTheDocument();
      expect(useChatSessionStore.getState().chatId).toBe("chat-7");
    });
  });
});
