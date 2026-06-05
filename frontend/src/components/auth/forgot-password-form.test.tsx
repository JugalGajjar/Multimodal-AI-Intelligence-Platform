import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
}));

import { ForgotPasswordForm } from "./forgot-password-form";

describe("<ForgotPasswordForm />", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    pushMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs to /forgot-password and routes to /reset-password with email", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ message: "If the account exists..." }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<ForgotPasswordForm />);
    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.click(screen.getByRole("button", { name: /send code/i }));

    await waitFor(() =>
      expect(pushMock).toHaveBeenCalledWith(
        "/reset-password?email=a%40b.com",
      ),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
