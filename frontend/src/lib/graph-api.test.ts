import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchGraphSnapshot } from "./graph-api";

describe("graph-api", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function ok(body: unknown, status = 200) {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }

  it("GETs /api/v1/graph/snapshot with the Bearer token", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ nodes: [], links: [], node_count: 0, link_count: 0 }),
    );

    const result = await fetchGraphSnapshot("tok-abc");

    expect(result.node_count).toBe(0);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/graph\/snapshot$/);
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok-abc",
    });
  });

  it("appends limit_nodes and limit_links when provided", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ nodes: [], links: [], node_count: 0, link_count: 0 }),
    );

    await fetchGraphSnapshot("tok", { limit_nodes: 50, limit_links: 200 });

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("limit_nodes=50");
    expect(url).toContain("limit_links=200");
  });

  it("returns nodes and links arrays", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({
        nodes: [
          {
            id: "Qdrant",
            name: "Qdrant",
            type: "Technology",
            description: "vector DB",
            document_ids: ["doc-1"],
          },
        ],
        links: [
          {
            source: "MMAP",
            target: "Qdrant",
            relation: "uses",
          },
        ],
        node_count: 1,
        link_count: 1,
      }),
    );

    const res = await fetchGraphSnapshot("tok");

    expect(res.nodes).toHaveLength(1);
    expect(res.nodes[0].type).toBe("Technology");
    expect(res.links[0].relation).toBe("uses");
  });
});
