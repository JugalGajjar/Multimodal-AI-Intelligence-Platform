import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
}));

import { RegisterForm } from "./register-form";

const STRONG = "StrongP@ss1";

async function fillName() {
  await userEvent.type(screen.getByLabelText(/first name/i), "Jane");
  await userEvent.type(screen.getByLabelText(/last name/i), "Doe");
}

describe("<RegisterForm />", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    pushMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rejects a weak password before calling the API", async () => {
    render(<RegisterForm />);

    await fillName();
    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.type(screen.getByLabelText("Password"), "abcdefgh");
    await userEvent.type(
      screen.getByLabelText(/confirm password/i),
      "abcdefgh",
    );
    await userEvent.click(
      screen.getByRole("button", { name: /create account/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/password/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("validates that passwords match before calling the API", async () => {
    render(<RegisterForm />);

    await fillName();
    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.type(screen.getByLabelText("Password"), STRONG);
    await userEvent.type(
      screen.getByLabelText(/confirm password/i),
      `${STRONG}x`,
    );
    await userEvent.click(
      screen.getByRole("button", { name: /create account/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /passwords do not match/i,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("on success, registers and routes to /verify-email with email in query", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          email: "a@b.com",
          verification_sent: true,
          message: "Check your email for a verification code.",
        }),
        {
          status: 201,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    render(<RegisterForm />);
    await fillName();
    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.type(screen.getByLabelText("Password"), STRONG);
    await userEvent.type(screen.getByLabelText(/confirm password/i), STRONG);
    await userEvent.click(
      screen.getByRole("button", { name: /create account/i }),
    );

    await waitFor(() =>
      expect(pushMock).toHaveBeenCalledWith("/verify-email?email=a%40b.com"),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // Body shape includes the new fields
    const body = JSON.parse(
      (fetchMock.mock.calls[0][1] as RequestInit).body as string,
    );
    expect(body).toEqual({
      email: "a@b.com",
      password: STRONG,
      first_name: "Jane",
      last_name: "Doe",
    });
  });

  it("shows duplicate email message on 409", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Email already registered" }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<RegisterForm />);
    await fillName();
    await userEvent.type(screen.getByLabelText("Email"), "a@b.com");
    await userEvent.type(screen.getByLabelText("Password"), STRONG);
    await userEvent.type(screen.getByLabelText(/confirm password/i), STRONG);
    await userEvent.click(
      screen.getByRole("button", { name: /create account/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /already registered/i,
    );
  });

  it("shows disposable-domain message on 400", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "Disposable email addresses are not allowed." }),
        {
          status: 400,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    render(<RegisterForm />);
    await fillName();
    await userEvent.type(screen.getByLabelText("Email"), "a@mailinator.com");
    await userEvent.type(screen.getByLabelText("Password"), STRONG);
    await userEvent.type(screen.getByLabelText(/confirm password/i), STRONG);
    await userEvent.click(
      screen.getByRole("button", { name: /create account/i }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /disposable/i,
    );
  });
});
