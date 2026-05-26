import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

import { AuthGate } from "./auth-gate";
import { useAuthStore } from "@/store/auth";

describe("<AuthGate />", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    useAuthStore.getState().clearSession();
  });

  afterEach(() => {
    useAuthStore.getState().clearSession();
  });

  it("redirects to /login when there is no token", async () => {
    render(
      <AuthGate>
        <div data-testid="protected">secret content</div>
      </AuthGate>,
    );

    await waitFor(() => {
      expect(replaceMock).toHaveBeenCalledWith("/login");
    });
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();
  });

  it("renders children when a token is present", () => {
    useAuthStore.getState().setSession(
      { id: "u-1", email: "a@b.com" },
      "tok-abc",
    );

    render(
      <AuthGate>
        <div data-testid="protected">secret content</div>
      </AuthGate>,
    );

    expect(screen.getByTestId("protected")).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("does NOT redirect when a token is present", async () => {
    useAuthStore.getState().setSession(
      { id: "u-2", email: "x@y.com" },
      "tok-xyz",
    );

    render(
      <AuthGate>
        <p>ok</p>
      </AuthGate>,
    );

    // Give effects a tick to run.
    await new Promise((r) => setTimeout(r, 0));
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
