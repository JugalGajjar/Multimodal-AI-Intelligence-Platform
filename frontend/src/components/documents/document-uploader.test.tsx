import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentUploader } from "./document-uploader";
import { useAuthStore } from "@/store/auth";

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
    ),
  };
}

describe("<DocumentUploader />", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
    useAuthStore.getState().setSession(
      { id: "u-1", email: "a@b.com" },
      "tok-abc",
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    useAuthStore.getState().clearSession();
  });

  function makeFile(name = "hello.pdf", type = "application/pdf"): File {
    return new File([new Uint8Array([1, 2, 3, 4])], name, { type });
  }

  it("upload button is disabled until a file is chosen", async () => {
    renderWithQuery(<DocumentUploader />);

    const button = screen.getByRole("button", { name: /upload/i });
    expect(button).toBeDisabled();

    await userEvent.upload(
      screen.getByLabelText(/file/i) as HTMLInputElement,
      makeFile(),
    );

    expect(button).not.toBeDisabled();
  });

  it("invalidates the documents query on successful upload", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "d-1",
          filename: "hello.pdf",
          content_type: "application/pdf",
          size_bytes: 4,
          status: "uploaded",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );

    const { queryClient } = renderWithQuery(<DocumentUploader />);
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    await userEvent.upload(
      screen.getByLabelText(/file/i) as HTMLInputElement,
      makeFile(),
    );
    await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));

    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["documents"] });
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows 'Unsupported file type' on 415", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unsupported" }), {
        status: 415,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithQuery(<DocumentUploader />);
    // Use an allowed-by-`accept` MIME for the input — the 415 comes from
    // the mocked backend response, not from client-side accept filtering.
    await userEvent.upload(
      screen.getByLabelText(/file/i) as HTMLInputElement,
      makeFile(),
    );
    await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /unsupported file type/i,
    );
  });

  it("shows 'File is too large' on 413", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "too big" }), {
        status: 413,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithQuery(<DocumentUploader />);
    await userEvent.upload(
      screen.getByLabelText(/file/i) as HTMLInputElement,
      makeFile(),
    );
    await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/too large/i);
  });

  it("shows 'File is empty' on 400", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "empty" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithQuery(<DocumentUploader />);
    await userEvent.upload(
      screen.getByLabelText(/file/i) as HTMLInputElement,
      makeFile(),
    );
    await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/empty/i);
  });

  it("shows generic message on other failures", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("", { status: 500, statusText: "Internal Server Error" }),
    );

    renderWithQuery(<DocumentUploader />);
    await userEvent.upload(
      screen.getByLabelText(/file/i) as HTMLInputElement,
      makeFile(),
    );
    await userEvent.click(screen.getByRole("button", { name: /^upload$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /upload failed/i,
    );
  });
});
