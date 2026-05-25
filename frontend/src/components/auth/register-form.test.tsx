import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
}));

import { RegisterForm } from "./register-form";
import { useAuthStore } from "@/store/auth";

describe("<RegisterForm />", () => {
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

  it("validates that passwords match before calling the API", async () => {
    render(<RegisterForm />);

    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.type(screen.getByLabelText("Password"), "abcdefgh");
    await userEvent.type(
      screen.getByLabelText(/confirm password/i),
      "different",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /create account/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /passwords do not match/i,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("on success, registers, logs in, fetches /me, sets session, routes to /dashboard", async () => {
    const user = {
      id: "u-1",
      email: "a@b.com",
      created_at: "2025-01-01T00:00:00Z",
    };
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify(user), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ access_token: "tok-abc", token_type: "bearer" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(user), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    render(<RegisterForm />);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.type(screen.getByLabelText("Password"), "abcdefgh");
    await userEvent.type(
      screen.getByLabelText(/confirm password/i),
      "abcdefgh",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /create account/i }),
    );

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/dashboard"));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(useAuthStore.getState().token).toBe("tok-abc");
  });

  it("shows duplicate email message on 409", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Email already registered" }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<RegisterForm />);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.type(screen.getByLabelText("Password"), "abcdefgh");
    await userEvent.type(
      screen.getByLabelText(/confirm password/i),
      "abcdefgh",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /create account/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /already registered/i,
    );
  });
});
