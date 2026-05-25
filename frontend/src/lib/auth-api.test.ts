import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchCurrentUser,
  loginUser,
  registerUser,
} from "./auth-api";

describe("auth-api", () => {
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

  it("registerUser POSTs email+password to /api/v1/auth/register", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ id: "u1", email: "a@b.com", created_at: "2025-01-01T00:00:00Z" }, 201),
    );

    const user = await registerUser("a@b.com", "abcdefgh");

    expect(user.email).toBe("a@b.com");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/auth\/register$/);
    expect((init as RequestInit).method).toBe("POST");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      email: "a@b.com",
      password: "abcdefgh",
    });
  });

  it("loginUser POSTs to /api/v1/auth/login and returns token", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ access_token: "tok-xyz", token_type: "bearer" }),
    );

    const data = await loginUser("a@b.com", "abcdefgh");

    expect(data.access_token).toBe("tok-xyz");
    expect(data.token_type).toBe("bearer");
    const [url] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/auth\/login$/);
  });

  it("fetchCurrentUser sends Authorization: Bearer header", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ id: "u1", email: "a@b.com", created_at: "2025-01-01T00:00:00Z" }),
    );

    const user = await fetchCurrentUser("tok-xyz");

    expect(user.id).toBe("u1");
    const [, init] = fetchMock.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer tok-xyz");
  });
});
