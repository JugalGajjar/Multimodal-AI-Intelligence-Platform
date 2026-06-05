import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
const searchGetMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
  useSearchParams: () => ({ get: searchGetMock }),
}));

import { ResetPasswordForm } from "./reset-password-form";
import { useAuthStore } from "@/store/auth";

const STRONG = "NewP@ssw0rd";

describe("<ResetPasswordForm />", () => {
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

  it("submits code + new password and logs in", async () => {
    searchGetMock.mockReturnValue("a@b.com");

    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ access_token: "tok-r", token_type: "bearer" }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
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

    render(<ResetPasswordForm />);
    await userEvent.type(screen.getByLabelText(/reset code/i), "ABCD1234");
    await userEvent.type(screen.getByLabelText(/^new password$/i), STRONG);
    await userEvent.type(screen.getByLabelText(/confirm new password/i), STRONG);
    await userEvent.click(
      screen.getByRole("button", { name: /reset password/i }),
    );

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/dashboard"));
    expect(useAuthStore.getState().token).toBe("tok-r");
  });

  it("rejects mismatched confirmation client-side", async () => {
    searchGetMock.mockReturnValue("a@b.com");

    render(<ResetPasswordForm />);
    await userEvent.type(screen.getByLabelText(/reset code/i), "ABCD1234");
    await userEvent.type(screen.getByLabelText(/^new password$/i), STRONG);
    await userEvent.type(
      screen.getByLabelText(/confirm new password/i),
      "different",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /reset password/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /do not match/i,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
