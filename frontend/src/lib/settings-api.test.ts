import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchChatModels,
  fetchChatSettings,
  updateChatSettings,
} from "./settings-api";

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
    fetchMock.mockResolvedValueOnce(
      ok({ rag_mode: "strict", web_max_results: 5, chat_model: null }),
    );

    const res = await fetchChatSettings("tok");

    expect(res).toEqual({
      rag_mode: "strict",
      web_max_results: 5,
      chat_model: null,
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/auth\/settings$/);
    expect((init as RequestInit).method).toBeUndefined();
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok",
    });
  });

  it("updateChatSettings PATCHes only the provided fields", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ rag_mode: "regular", web_max_results: 5, chat_model: null }),
    );

    const res = await updateChatSettings("tok", { rag_mode: "regular" });

    expect(res.rag_mode).toBe("regular");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/auth\/settings$/);
    expect((init as RequestInit).method).toBe("PATCH");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      rag_mode: "regular",
    });
  });

  it("updateChatSettings can send chat_model: null to revert to default", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ rag_mode: "strict", web_max_results: 5, chat_model: null }),
    );

    await updateChatSettings("tok", { chat_model: null });

    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      chat_model: null,
    });
  });

  it("fetchChatModels GETs /chat/models with Bearer token", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({
        default: "openai/gpt-oss-120b",
        models: [
          {
            id: "openai/gpt-oss-120b",
            label: "GPT-OSS 120B",
            provider: "Groq",
            category: "open-source",
            notes: "Default.",
            is_default: true,
          },
        ],
      }),
    );

    const res = await fetchChatModels("tok");

    expect(res.default).toBe("openai/gpt-oss-120b");
    expect(res.models).toHaveLength(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/chat\/models$/);
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok",
    });
  });
});
