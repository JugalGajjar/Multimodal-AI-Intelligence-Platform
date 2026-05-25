import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteDocument,
  formatBytes,
  listDocuments,
  uploadDocument,
} from "./documents-api";

describe("documents-api", () => {
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

  it("listDocuments sends Bearer token", async () => {
    fetchMock.mockResolvedValueOnce(ok({ items: [], total: 0 }));

    const res = await listDocuments("tok");

    expect(res.total).toBe(0);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/documents$/);
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer tok",
    });
  });

  it("uploadDocument sends multipart and DOES NOT set Content-Type", async () => {
    fetchMock.mockResolvedValueOnce(
      ok(
        {
          id: "d1",
          filename: "x.pdf",
          content_type: "application/pdf",
          size_bytes: 4,
          status: "uploaded",
          created_at: "2025-01-01T00:00:00Z",
          updated_at: "2025-01-01T00:00:00Z",
        },
        201,
      ),
    );

    const file = new File([new Uint8Array([1, 2, 3, 4])], "x.pdf", {
      type: "application/pdf",
    });

    const doc = await uploadDocument("tok", file);

    expect(doc.filename).toBe("x.pdf");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/documents$/);
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
    expect(headers.Authorization).toBe("Bearer tok");
  });

  it("uploadDocument throws ApiError on non-2xx", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unsupported" }), {
        status: 415,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const file = new File([new Uint8Array([0])], "x.bin", {
      type: "application/octet-stream",
    });

    await expect(uploadDocument("tok", file)).rejects.toMatchObject({
      name: "ApiError",
      status: 415,
    });
  });

  it("deleteDocument issues DELETE with Bearer", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await deleteDocument("tok", "doc-1");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/documents\/doc-1$/);
    expect((init as RequestInit).method).toBe("DELETE");
  });

  it("formatBytes is human-friendly", () => {
    expect(formatBytes(500)).toBe("500 B");
    expect(formatBytes(1500)).toBe("1.5 KB");
    expect(formatBytes(1_500_000)).toBe("1.43 MB");
  });
});
