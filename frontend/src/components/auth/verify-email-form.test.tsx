import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
const searchGetMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
  useSearchParams: () => ({ get: searchGetMock }),
}));

import { VerifyEmailForm } from "./verify-email-form";
import { useAuthStore } from "@/store/auth";

describe("<VerifyEmailForm />", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    pushMock.mockReset();
    searchGetMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    useAuthStore.getState().clearSession();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("prefills email from ?email=... and verifies on submit", async () => {
    searchGetMock.mockReturnValue("a@b.com");

    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ access_token: "tok-v", token_type: "bearer" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "u1",
            email: "a@b.com",
            is_verified: true,
            created_at: "2026-01-01T00:00:00Z",
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );

    render(<VerifyEmailForm />);
    expect(screen.getByLabelText("Email")).toHaveValue("a@b.com");

    await userEvent.type(
      screen.getByLabelText(/verification code/i),
      "ABCD1234",
    );
    await userEvent.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/dashboard"));
    expect(useAuthStore.getState().token).toBe("tok-v");
  });

  it("shows invalid/expired message on 400", async () => {
    searchGetMock.mockReturnValue("");

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Invalid code or email." }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<VerifyEmailForm />);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.type(
      screen.getByLabelText(/verification code/i),
      "BADCODE1",
    );
    await userEvent.click(screen.getByRole("button", { name: /^verify$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /invalid or expired/i,
    );
  });

  it("upper-cases the code and strips whitespace", async () => {
    searchGetMock.mockReturnValue("a@b.com");

    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ access_token: "x", token_type: "bearer" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "u1",
          email: "a@b.com",
          is_verified: true,
          created_at: "x",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<VerifyEmailForm />);
    await userEvent.type(
      screen.getByLabelText(/verification code/i),
      "abcd1234",
    );
    await userEvent.click(screen.getByRole("button", { name: /^verify$/i }));

    await waitFor(() => {
      const body = JSON.parse(
        (fetchMock.mock.calls[0][1] as RequestInit).body as string,
      );
      expect(body.code).toBe("ABCD1234");
    });
  });
});
