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

/**
 * URL-routed fetch mock. Tests register responses per URL pattern, so the
 * order of in-flight TanStack Query requests doesn't matter.
 */
type Handler = (init?: RequestInit) => Response | Promise<Response>;

function createRoutedFetch() {
  const routes: { pattern: RegExp; handler: Handler }[] = [];

  function add(pattern: RegExp, handler: Handler) {
    routes.push({ pattern, handler });
  }

  function impl(url: string | URL, init?: RequestInit) {
    const u = String(url);
    for (const route of routes) {
      if (route.pattern.test(u)) return Promise.resolve(route.handler(init));
    }
    return Promise.resolve(
      new Response("no route", { status: 599, statusText: "no test route" }),
    );
  }

  return { add, impl };
}

describe("<DocumentsList />", () => {
  beforeEach(() => {
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
    const r = createRoutedFetch();
    r.add(/\/documents$/, () => jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", vi.fn(r.impl));

    renderWithQuery(<DocumentsList />);

    expect(
      await screen.findByText(/no documents yet/i),
    ).toBeInTheDocument();
  });

  it("renders filename, size summary, and status badge for each document", async () => {
    const r = createRoutedFetch();
    r.add(/\/documents$/, () =>
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
    r.add(/\/chunks$/, () =>
      jsonResponse({ document_id: "d-1", total: 4, items: [] }),
    );
    vi.stubGlobal("fetch", vi.fn(r.impl));

    renderWithQuery(<DocumentsList />);

    expect(await screen.findByText("a.pdf")).toBeInTheDocument();
    expect(screen.getByText("b.txt")).toBeInTheDocument();
    expect(screen.getByText("processed")).toBeInTheDocument();
    expect(screen.getByText("processing")).toBeInTheDocument();
    expect(screen.getByText(/2 documents/)).toBeInTheDocument();
  });

  it("shows chunk count next to a processed document", async () => {
    const r = createRoutedFetch();
    r.add(/\/documents$/, () =>
      jsonResponse({
        items: [makeDoc({ id: "d-cc", status: "processed" })],
        total: 1,
      }),
    );
    r.add(/\/chunks$/, () =>
      jsonResponse({ document_id: "d-cc", total: 7, items: [] }),
    );
    vi.stubGlobal("fetch", vi.fn(r.impl));

    renderWithQuery(<DocumentsList />);

    expect(await screen.findByText(/7 chunks/i)).toBeInTheDocument();
  });

  it("disables the 'View text' button until the document is processed", async () => {
    const r = createRoutedFetch();
    r.add(/\/documents$/, () =>
      jsonResponse({
        items: [makeDoc({ status: "processing" })],
        total: 1,
      }),
    );
    vi.stubGlobal("fetch", vi.fn(r.impl));

    renderWithQuery(<DocumentsList />);

    const viewBtn = await screen.findByRole("button", { name: /view text/i });
    expect(viewBtn).toBeDisabled();
  });

  it("clicking 'View text' fetches and shows extracted text inline", async () => {
    const r = createRoutedFetch();
    r.add(/\/documents$/, () =>
      jsonResponse({
        items: [makeDoc({ id: "d-x", status: "processed" })],
        total: 1,
      }),
    );
    r.add(/\/chunks$/, () =>
      jsonResponse({ document_id: "d-x", total: 3, items: [] }),
    );
    r.add(/\/text$/, () =>
      jsonResponse({
        id: "d-x",
        status: "processed",
        extracted_text: "the hidden text from OCR",
      }),
    );
    const spy = vi.fn(r.impl);
    vi.stubGlobal("fetch", spy);

    renderWithQuery(<DocumentsList />);

    await userEvent.click(
      await screen.findByRole("button", { name: /view text/i }),
    );

    expect(
      await screen.findByText(/the hidden text from ocr/i),
    ).toBeInTheDocument();
    const textCall = spy.mock.calls.find((c) =>
      String(c[0]).endsWith("/text"),
    );
    expect(textCall).toBeDefined();
  });

  it("toggles text panel off when the button is clicked again", async () => {
    const r = createRoutedFetch();
    r.add(/\/documents$/, () =>
      jsonResponse({
        items: [makeDoc({ id: "d-y", status: "processed" })],
        total: 1,
      }),
    );
    r.add(/\/chunks$/, () =>
      jsonResponse({ document_id: "d-y", total: 1, items: [] }),
    );
    r.add(/\/text$/, () =>
      jsonResponse({
        id: "d-y",
        status: "processed",
        extracted_text: "visible body",
      }),
    );
    vi.stubGlobal("fetch", vi.fn(r.impl));

    renderWithQuery(<DocumentsList />);

    await userEvent.click(
      await screen.findByRole("button", { name: /view text/i }),
    );
    expect(await screen.findByText("visible body")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /hide text/i }));
    await waitFor(() => {
      expect(screen.queryByText("visible body")).not.toBeInTheDocument();
    });
  });

  it("clicking 'Delete' calls DELETE on the document endpoint", async () => {
    const r = createRoutedFetch();
    let listCalls = 0;
    r.add(/\/documents$/, (init) => {
      listCalls++;
      if ((init?.method ?? "GET") === "GET") {
        return jsonResponse({
          items: listCalls === 1 ? [makeDoc({ id: "d-del" })] : [],
          total: listCalls === 1 ? 1 : 0,
        });
      }
      return new Response(null, { status: 204 });
    });
    r.add(/\/chunks$/, () =>
      jsonResponse({ document_id: "d-del", total: 0, items: [] }),
    );
    r.add(/\/documents\/d-del$/, () => new Response(null, { status: 204 }));
    const spy = vi.fn(r.impl);
    vi.stubGlobal("fetch", spy);

    renderWithQuery(<DocumentsList />);

    await userEvent.click(
      await screen.findByRole("button", { name: /^delete$/i }),
    );

    await waitFor(() => {
      const deleteCall = spy.mock.calls.find(
        (call) => (call[1] as RequestInit | undefined)?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
      expect(String(deleteCall![0])).toMatch(/\/api\/v1\/documents\/d-del$/);
    });
  });

  it("renders an error message when the list query fails", async () => {
    const r = createRoutedFetch();
    r.add(/\/documents$/, () =>
      new Response("nope", {
        status: 500,
        statusText: "Internal Server Error",
      }),
    );
    vi.stubGlobal("fetch", vi.fn(r.impl));

    renderWithQuery(<DocumentsList />);

    expect(
      await screen.findByText(/failed to load documents/i),
    ).toBeInTheDocument();
  });
});
