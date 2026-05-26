import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsList } from "./documents-list";
import { useAuthStore } from "@/store/auth";
import type { DocumentItem } from "@/lib/documents-api";

function renderWithQuery(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>,
  );
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function makeDoc(overrides: Partial<DocumentItem> = {}): DocumentItem {
  return {
    id: "d-1",
    filename: "hello.pdf",
    content_type: "application/pdf",
    size_bytes: 1024,
    status: "processed",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("<DocumentsList />", () => {
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

  it("shows empty state when there are no documents", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));

    renderWithQuery(<DocumentsList />);

    expect(
      await screen.findByText(/no documents yet/i),
    ).toBeInTheDocument();
  });

  it("renders filename, size summary, and status badge for each document", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [
          makeDoc({ id: "d-1", filename: "a.pdf", status: "processed" }),
          makeDoc({
            id: "d-2",
            filename: "b.txt",
            content_type: "text/plain",
            status: "processing",
            size_bytes: 500,
          }),
        ],
        total: 2,
      }),
    );

    renderWithQuery(<DocumentsList />);

    expect(await screen.findByText("a.pdf")).toBeInTheDocument();
    expect(screen.getByText("b.txt")).toBeInTheDocument();
    expect(screen.getByText("processed")).toBeInTheDocument();
    expect(screen.getByText("processing")).toBeInTheDocument();
    expect(screen.getByText(/2 documents/)).toBeInTheDocument();
  });

  it("disables the 'View text' button until the document is processed", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        items: [makeDoc({ status: "processing" })],
        total: 1,
      }),
    );

    renderWithQuery(<DocumentsList />);

    const viewBtn = await screen.findByRole("button", { name: /view text/i });
    expect(viewBtn).toBeDisabled();
  });

  it("clicking 'View text' fetches and shows extracted text inline", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          items: [makeDoc({ id: "d-x", status: "processed" })],
          total: 1,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: "d-x",
          status: "processed",
          extracted_text: "the hidden text from OCR",
        }),
      );

    renderWithQuery(<DocumentsList />);

    await userEvent.click(
      await screen.findByRole("button", { name: /view text/i }),
    );

    expect(
      await screen.findByText(/the hidden text from ocr/i),
    ).toBeInTheDocument();

    // text fetch went to /text endpoint
    const textUrl = fetchMock.mock.calls[1][0] as string;
    expect(textUrl).toMatch(/\/api\/v1\/documents\/d-x\/text$/);
  });

  it("toggles text panel off when the button is clicked again", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          items: [makeDoc({ id: "d-y", status: "processed" })],
          total: 1,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          id: "d-y",
          status: "processed",
          extracted_text: "visible body",
        }),
      );

    renderWithQuery(<DocumentsList />);

    const toggle = await screen.findByRole("button", { name: /view text/i });
    await userEvent.click(toggle);
    expect(
      await screen.findByText("visible body"),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /hide text/i }),
    );
    await waitFor(() => {
      expect(screen.queryByText("visible body")).not.toBeInTheDocument();
    });
  });

  it("clicking 'Delete' calls DELETE on the document endpoint", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          items: [makeDoc({ id: "d-del" })],
          total: 1,
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      // refetch after invalidation
      .mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));

    renderWithQuery(<DocumentsList />);

    await userEvent.click(
      await screen.findByRole("button", { name: /^delete$/i }),
    );

    await waitFor(() => {
      const deleteCall = fetchMock.mock.calls.find(
        (call) => (call[1] as RequestInit | undefined)?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
      expect(deleteCall![0]).toMatch(/\/api\/v1\/documents\/d-del$/);
    });
  });

  it("renders an error message when the list query fails", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("nope", { status: 500, statusText: "Internal Server Error" }),
    );

    renderWithQuery(<DocumentsList />);

    expect(
      await screen.findByText(/failed to load documents/i),
    ).toBeInTheDocument();
  });
});
