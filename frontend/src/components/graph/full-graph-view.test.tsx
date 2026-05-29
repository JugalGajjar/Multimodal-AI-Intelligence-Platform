import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Stub the canvas-heavy graph component. We expose the props we care about so
// we can drive the side-panel test deterministically (i.e. simulate a node click).
vi.mock("@/components/graph/knowledge-graph", () => ({
  KnowledgeGraph: (props: {
    nodes: { id: string; name: string; type: string; description: string }[];
    onNodeClick?: (n: {
      id: string;
      name: string;
      type: string;
      description: string;
      document_ids: string[];
    }) => void;
  }) => (
    <div
      data-testid="kg-stub"
      data-node-count={props.nodes.length}
    >
      {props.nodes.map((n) => (
        <button
          key={n.id}
          type="button"
          data-testid={`kg-node-${n.id}`}
          onClick={() =>
            props.onNodeClick?.({
              id: n.id,
              name: n.name,
              type: n.type,
              description: n.description,
              document_ids: [],
            })
          }
        >
          {n.name}
        </button>
      ))}
    </div>
  ),
}));

import { FullGraphView } from "./full-graph-view";
import { useAuthStore } from "@/store/auth";

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
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

const SAMPLE = {
  nodes: [
    {
      id: "Qdrant",
      name: "Qdrant",
      type: "Technology",
      description: "open-source vector DB",
      document_ids: ["doc-1"],
    },
    {
      id: "Cosine Distance",
      name: "Cosine Distance",
      type: "Concept",
      description: "similarity metric",
      document_ids: ["doc-1"],
    },
    {
      id: "Jugal Gajjar",
      name: "Jugal Gajjar",
      type: "Person",
      description: "author",
      document_ids: ["doc-1"],
    },
  ],
  links: [
    { source: "Qdrant", target: "Cosine Distance", relation: "uses" },
    {
      source: "Jugal Gajjar",
      target: "Qdrant",
      relation: "builds with",
    },
  ],
  node_count: 3,
  link_count: 2,
};

describe("<FullGraphView />", () => {
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

  it("shows the loading state initially", async () => {
    let resolveFetch!: (r: Response) => void;
    const deferred = new Promise<Response>((r) => (resolveFetch = r));
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(deferred));

    renderWithQuery(<FullGraphView />);

    expect(await screen.findByTestId("kg-loading")).toBeInTheDocument();

    resolveFetch(jsonResponse(SAMPLE));
    await waitFor(() =>
      expect(screen.queryByTestId("kg-loading")).not.toBeInTheDocument(),
    );
  });

  it("renders nodes + relationship counts on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(SAMPLE)));

    renderWithQuery(<FullGraphView />);

    expect(await screen.findByTestId("kg-stub")).toBeInTheDocument();
    expect(screen.getByTestId("kg-node-count")).toHaveTextContent("3 entities");
    expect(screen.getByTestId("kg-link-count")).toHaveTextContent(
      "2 relationships",
    );
  });

  it("renders the empty state when the user has no entities", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ nodes: [], links: [], node_count: 0, link_count: 0 }),
        ),
    );

    renderWithQuery(<FullGraphView />);

    expect(await screen.findByTestId("kg-empty-full")).toBeInTheDocument();
    expect(screen.queryByTestId("kg-stub")).not.toBeInTheDocument();
  });

  it("renders the error state on a failed request", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("nope", { status: 500, statusText: "Internal" }),
        ),
    );

    renderWithQuery(<FullGraphView />);

    expect(await screen.findByTestId("kg-error")).toBeInTheDocument();
  });

  it("filters the graph by search input (1-hop expansion)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(SAMPLE)));

    renderWithQuery(<FullGraphView />);
    await screen.findByTestId("kg-stub");

    // Typing "qdrant" matches Qdrant + pulls in its 1-hop neighbours
    // (Cosine Distance & Jugal Gajjar via the two links).
    await userEvent.type(screen.getByTestId("kg-search"), "qdrant");

    await waitFor(() => {
      const stub = screen.getByTestId("kg-stub");
      // Direct match plus both neighbours = 3 nodes in this fixture.
      expect(stub.getAttribute("data-node-count")).toBe("3");
    });

    // Now narrow the search to something more specific.
    await userEvent.clear(screen.getByTestId("kg-search"));
    await userEvent.type(screen.getByTestId("kg-search"), "cosine");
    await waitFor(() => {
      // "Cosine Distance" matches; only Qdrant is a 1-hop neighbour.
      const stub = screen.getByTestId("kg-stub");
      expect(stub.getAttribute("data-node-count")).toBe("2");
    });
  });

  it("clicking a node opens the side panel with its description + relations", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(SAMPLE)));

    renderWithQuery(<FullGraphView />);
    await screen.findByTestId("kg-stub");

    // Before click — panel shows the "click a node" hint, not detail content.
    expect(screen.queryByTestId("kg-selected")).not.toBeInTheDocument();
    expect(screen.getByText(/click a node/i)).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("kg-node-Qdrant"));

    const panel = await screen.findByTestId("kg-selected");
    // Type + description appear
    expect(panel).toHaveTextContent("Qdrant");
    expect(panel).toHaveTextContent("Technology");
    expect(panel).toHaveTextContent(/open-source vector DB/i);
    // Outgoing edge (Qdrant → Cosine Distance via "uses")
    expect(panel).toHaveTextContent("uses");
    expect(panel).toHaveTextContent("Cosine Distance");
    // Incoming edge (Jugal Gajjar → Qdrant via "builds with")
    expect(panel).toHaveTextContent("builds with");
    expect(panel).toHaveTextContent("Jugal Gajjar");
  });

  it("closing the side panel returns to the placeholder", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(SAMPLE)));

    renderWithQuery(<FullGraphView />);
    await screen.findByTestId("kg-stub");
    await userEvent.click(screen.getByTestId("kg-node-Qdrant"));
    await screen.findByTestId("kg-selected");

    await userEvent.click(screen.getByTestId("kg-close-details"));
    await waitFor(() =>
      expect(screen.queryByTestId("kg-selected")).not.toBeInTheDocument(),
    );
    expect(screen.getByText(/click a node/i)).toBeInTheDocument();
  });

  it("back-to-dashboard link points at /dashboard", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(SAMPLE)));

    renderWithQuery(<FullGraphView />);

    const link = await screen.findByTestId("back-to-dashboard");
    expect(link).toHaveAttribute("href", "/dashboard");
  });

  it("calls the snapshot API with the bearer token and a limit", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(SAMPLE));
    vi.stubGlobal("fetch", fetchMock);

    renderWithQuery(<FullGraphView />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/graph\/snapshot(\?.*)?$/);
    expect(url).toContain("limit_nodes=500");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok-abc",
    });
  });
});
