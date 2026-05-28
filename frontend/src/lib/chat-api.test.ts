import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { sendChatQuery } from "./chat-api";

describe("chat-api", () => {
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

  it("POSTs to /api/v1/chat with Bearer token and JSON body", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({
        answer: "the answer",
        citations: [],
        model: "deepseek/deepseek-v4-flash:free",
        used_context: false,
      }),
    );

    const res = await sendChatQuery("tok-abc", {
      query: "hi",
      top_k: 3,
    });

    expect(res.answer).toBe("the answer");
    expect(res.used_context).toBe(false);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/chat$/);
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok-abc",
      "Content-Type": "application/json",
    });
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      query: "hi",
      top_k: 3,
    });
  });

  it("returns citations array when present", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({
        answer: "x",
        citations: [
          {
            chunk_id: "c1",
            document_id: "d1",
            chunk_index: 0,
            score: 0.7,
            text_preview: "snippet",
          },
        ],
        model: "m",
        used_context: true,
      }),
    );

    const res = await sendChatQuery("tok", { query: "q" });

    expect(res.citations).toHaveLength(1);
    expect(res.citations[0].score).toBeCloseTo(0.7);
  });

  it("throws ApiError on non-2xx (e.g. 429 rate-limit)", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "rate limited" }), {
        status: 429,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(sendChatQuery("tok", { query: "q" })).rejects.toMatchObject({
      name: "ApiError",
      status: 429,
    });
  });

  it("throws ApiError on 503 when key missing", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "no key" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(sendChatQuery("tok", { query: "q" })).rejects.toMatchObject({
      status: 503,
    });
  });
});
