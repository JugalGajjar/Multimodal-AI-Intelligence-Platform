import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchChatSettings, updateChatSettings } from "./settings-api";

describe("settings-api", () => {
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

  it("fetchChatSettings GETs with Bearer token", async () => {
    fetchMock.mockResolvedValueOnce(ok({ rag_mode: "strict", web_max_results: 5 }));

    const res = await fetchChatSettings("tok");

    expect(res).toEqual({ rag_mode: "strict", web_max_results: 5 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/auth\/settings$/);
    expect((init as RequestInit).method).toBeUndefined();
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok",
    });
  });

  it("updateChatSettings PATCHes only the provided fields", async () => {
    fetchMock.mockResolvedValueOnce(ok({ rag_mode: "regular", web_max_results: 5 }));

    const res = await updateChatSettings("tok", { rag_mode: "regular" });

    expect(res.rag_mode).toBe("regular");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/auth\/settings$/);
    expect((init as RequestInit).method).toBe("PATCH");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      rag_mode: "regular",
    });
  });
});
