import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchCurrentUser,
  forgotPassword,
  loginUser,
  registerUser,
  resendVerification,
  resetPassword,
  verifyEmail,
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

  function lastCall() {
    const [url, init] = fetchMock.mock.calls[fetchMock.mock.calls.length - 1];
    return { url: url as string, init: init as RequestInit };
  }

  it("registerUser POSTs to /api/v1/auth/register and returns RegisterResponse", async () => {
    fetchMock.mockResolvedValueOnce(
      ok(
        {
          email: "a@b.com",
          verification_sent: true,
          message: "Check your email for a verification code.",
        },
        201,
      ),
    );

    const resp = await registerUser("a@b.com", "StrongP@ss1");

    expect(resp.email).toBe("a@b.com");
    expect(resp.verification_sent).toBe(true);
    const { url, init } = lastCall();
    expect(url).toMatch(/\/api\/v1\/auth\/register$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      email: "a@b.com",
      password: "StrongP@ss1",
    });
  });

  it("loginUser POSTs to /api/v1/auth/login and returns token", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ access_token: "tok-xyz", token_type: "bearer" }),
    );

    const data = await loginUser("a@b.com", "StrongP@ss1");

    expect(data.access_token).toBe("tok-xyz");
    expect(data.token_type).toBe("bearer");
    expect(lastCall().url).toMatch(/\/api\/v1\/auth\/login$/);
  });

  it("verifyEmail POSTs email+code and returns token", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ access_token: "tok-verified", token_type: "bearer" }),
    );

    const data = await verifyEmail("a@b.com", "ABCD1234");

    expect(data.access_token).toBe("tok-verified");
    const { url, init } = lastCall();
    expect(url).toMatch(/\/api\/v1\/auth\/verify-email$/);
    expect(JSON.parse(init.body as string)).toEqual({
      email: "a@b.com",
      code: "ABCD1234",
    });
  });

  it("resendVerification POSTs to /api/v1/auth/resend-verification", async () => {
    fetchMock.mockResolvedValueOnce(ok({ message: "sent" }));

    const data = await resendVerification("a@b.com");

    expect(data.message).toBe("sent");
    const { url, init } = lastCall();
    expect(url).toMatch(/\/api\/v1\/auth\/resend-verification$/);
    expect(JSON.parse(init.body as string)).toEqual({ email: "a@b.com" });
  });

  it("forgotPassword POSTs to /api/v1/auth/forgot-password", async () => {
    fetchMock.mockResolvedValueOnce(ok({ message: "sent" }));

    const data = await forgotPassword("a@b.com");

    expect(data.message).toBe("sent");
    expect(lastCall().url).toMatch(/\/api\/v1\/auth\/forgot-password$/);
  });

  it("resetPassword POSTs email+code+new_password and returns token", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({ access_token: "tok-reset", token_type: "bearer" }),
    );

    const data = await resetPassword("a@b.com", "ABCD1234", "NewP@ss1");

    expect(data.access_token).toBe("tok-reset");
    const { url, init } = lastCall();
    expect(url).toMatch(/\/api\/v1\/auth\/reset-password$/);
    expect(JSON.parse(init.body as string)).toEqual({
      email: "a@b.com",
      code: "ABCD1234",
      new_password: "NewP@ss1",
    });
  });

  it("fetchCurrentUser sends Authorization: Bearer header", async () => {
    fetchMock.mockResolvedValueOnce(
      ok({
        id: "u1",
        email: "a@b.com",
        is_verified: true,
        created_at: "2026-01-01T00:00:00Z",
      }),
    );

    const user = await fetchCurrentUser("tok-xyz");

    expect(user.id).toBe("u1");
    expect(user.is_verified).toBe(true);
    const headers = (lastCall().init.headers as Record<string, string>);
    expect(headers.Authorization).toBe("Bearer tok-xyz");
  });
});
