import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
}));

import { LoginForm } from "./login-form";
import { useAuthStore } from "@/store/auth";

const STRONG = "StrongP@ss1";

describe("<LoginForm />", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    pushMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    useAuthStore.getState().clearSession();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls /login then /me, stores session, and routes to /dashboard", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ access_token: "tok-abc", token_type: "bearer" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "u-1",
            email: "a@b.com",
            is_verified: true,
            created_at: "2026-01-01T00:00:00Z",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(<LoginForm />);

    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.type(screen.getByLabelText("Password"), STRONG);
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/dashboard");
    });

    const state = useAuthStore.getState();
    expect(state.token).toBe("tok-abc");
    expect(state.user?.email).toBe("a@b.com");
    expect(state.user?.isVerified).toBe(true);
    expect(state.isAuthenticated).toBe(true);
  });

  it("shows 'Invalid email or password' on 401", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Invalid email or password" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<LoginForm />);

    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrongpassword");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /invalid email or password/i,
    );
    expect(pushMock).not.toHaveBeenCalled();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it("offers a verify-email link when the account isn't verified (403)", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "Email not verified. Check your inbox for the code." }),
        { status: 403, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<LoginForm />);

    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.type(screen.getByLabelText("Password"), STRONG);
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/isn(’|')t verified/i);
    const link = screen.getByRole("link", {
      name: /enter your verification code/i,
    });
    expect(link).toHaveAttribute("href", "/verify-email?email=a%40b.com");
  });
});
