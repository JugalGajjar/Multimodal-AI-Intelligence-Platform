import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteChat,
  getChat,
  listChats,
  renameChat,
  searchChats,
} from "./chats-api";

describe("chats-api", () => {
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

  it("listChats GETs /chats with Bearer token", async () => {
    fetchMock.mockResolvedValueOnce(ok({ items: [], total: 0 }));

    const res = await listChats("tok");

    expect(res.total).toBe(0);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/chats$/);
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok",
    });
  });

  it("getChat GETs the transcript", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ id: "c1", title: "t", summary: null, messages: [] }),
    );

    await getChat("tok", "c1");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/v1\/chats\/c1$/);
  });

  it("renameChat PATCHes the title", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ id: "c1", title: "renamed", summary: null, message_count: 2 }),
    );

    const res = await renameChat("tok", "c1", "renamed");

    expect(res.title).toBe("renamed");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/chats\/c1$/);
    expect((init as RequestInit).method).toBe("PATCH");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      title: "renamed",
    });
  });

  it("searchChats URL-encodes the query", async () => {
    fetchMock.mockResolvedValueOnce(ok({ items: [], total: 0, query: "a&b" }));

    await searchChats("tok", "a&b");
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/chats\/search\?q=a%26b$/);
  });

  it("deleteChat treats 204 as success", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(deleteChat("tok", "c1")).resolves.toBeUndefined();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/chats\/c1$/);
    expect((init as RequestInit).method).toBe("DELETE");
  });

  it("deleteChat throws on 404", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Chat not found" }), { status: 404 }),
    );

    await expect(deleteChat("tok", "missing")).rejects.toThrow(/404/);
  });
});
