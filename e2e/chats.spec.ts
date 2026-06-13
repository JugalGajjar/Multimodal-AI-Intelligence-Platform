import { expect, test } from "@playwright/test";

import { registerAndSignIn } from "./auth-helpers";

const CHAT_ID = "11111111-1111-1111-1111-111111111111";

function ssEvent(name: string, data: unknown): string {
  return `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
}

function sseFromAnswer(answer: string, chatId = CHAT_ID): string {
  const meta = {
    chat_id: chatId,
    intent: "chat",
    used_context: false,
    used_graph: false,
    used_web: false,
    model: "openai/gpt-oss-20b",
    citations: [],
    entities_used: [],
    web_citations: [],
    strict: false,
  };
  const half = Math.ceil(answer.length / 2);
  let out = ssEvent("meta", meta);
  if (answer.length > 0) {
    out += ssEvent("token", { text: answer.slice(0, half) });
    out += ssEvent("token", { text: answer.slice(half) });
  }
  out += ssEvent("done", { verification: null, strict_refusal: null });
  return out;
}

test.describe("Chat history", () => {
  test("thread persists across navigation; history page CRUD + search", async ({
    page,
  }) => {
    const codeword = "zebra-fixed-codeword";
    let chatTitle = "Remember the codeword zebra-fixed-codeword. What…";
    let deleted = false;

    // /chat/stream — fake the SSE stream the panel would receive from the real backend.
    let turn = 0;
    await page.route("**/api/v1/chat/stream", async (route) => {
      turn += 1;
      const answer =
        turn === 1
          ? `Got the codeword ${codeword}. RAG stands for retrieval-augmented generation.`
          : "It stands for retrieval-augmented generation.";
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseFromAnswer(answer),
      });
    });

    // /chats — list. Search hits /chats/search.
    await page.route(/\/api\/v1\/chats\?|\/api\/v1\/chats$/, async (route) => {
      if (deleted) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ items: [], total: 0 }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [
            {
              id: CHAT_ID,
              title: chatTitle,
              summary: "User asked about RAG.",
              message_count: 4,
              created_at: "2026-06-13T00:00:00Z",
              updated_at: "2026-06-13T00:00:00Z",
            },
          ],
          total: 1,
        }),
      });
    });

    await page.route(/\/api\/v1\/chats\/search/, async (route) => {
      const url = new URL(route.request().url());
      const q = url.searchParams.get("q") ?? "";
      const matches = chatTitle.includes(q) || q === codeword;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: matches
            ? [
                {
                  id: CHAT_ID,
                  title: chatTitle,
                  summary: "User asked about RAG.",
                  message_count: 4,
                  created_at: "2026-06-13T00:00:00Z",
                  updated_at: "2026-06-13T00:00:00Z",
                  snippet: `…matched ${q} in this chat…`,
                  match_source: "message",
                },
              ]
            : [],
          total: matches ? 1 : 0,
          query: q,
        }),
      });
    });

    // /chats/{id} — transcript. PATCH renames. DELETE marks the list empty.
    await page.route(new RegExp(`/api/v1/chats/${CHAT_ID}$`), async (route) => {
      const method = route.request().method();
      if (method === "PATCH") {
        const body = JSON.parse(route.request().postData() ?? "{}");
        chatTitle = body.title;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: CHAT_ID,
            title: chatTitle,
            summary: "User asked about RAG.",
            message_count: 4,
            created_at: "2026-06-13T00:00:00Z",
            updated_at: "2026-06-13T00:00:00Z",
          }),
        });
        return;
      }
      if (method === "DELETE") {
        deleted = true;
        await route.fulfill({ status: 204, body: "" });
        return;
      }
      // GET — transcript.
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: CHAT_ID,
          title: chatTitle,
          summary: "User asked about RAG.",
          created_at: "2026-06-13T00:00:00Z",
          updated_at: "2026-06-13T00:00:00Z",
          messages: [
            {
              id: "m1",
              seq: 0,
              role: "user",
              content: `Remember the codeword ${codeword}. What is RAG?`,
              created_at: "2026-06-13T00:00:00Z",
              citations: [],
              web_citations: [],
              verification: null,
              response_meta: null,
            },
            {
              id: "m2",
              seq: 1,
              role: "assistant",
              content: "RAG stands for retrieval-augmented generation.",
              created_at: "2026-06-13T00:00:01Z",
              citations: [],
              web_citations: [],
              verification: null,
              response_meta: { model: "openai/gpt-oss-20b" },
            },
          ],
        }),
      });
    });

    await registerAndSignIn(page, "chats");

    // Two turns on the dashboard.
    await page.getByLabel("Question").fill(`Remember the codeword ${codeword}. What is RAG?`);
    await page.getByRole("button", { name: /^send$/i }).click();
    await expect(page.getByTestId("chat-turn")).toHaveCount(1, { timeout: 15_000 });

    await page.getByLabel("Question").fill("What does it stand for?");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expect(page.getByTestId("chat-turn")).toHaveCount(2, { timeout: 15_000 });

    // Client-side navigation away and back — thread intact.
    await page.getByTestId("nav-your-documents").click();
    await expect(page).toHaveURL(/\/dashboard\/documents/);
    await page.getByTestId("nav-dashboard").click();
    await expect(page.getByTestId("chat-turn")).toHaveCount(2);

    // Chats page via sidebar.
    await page.getByTestId("nav-chats").click();
    await expect(page).toHaveURL(/\/dashboard\/chats/);
    const row = page.getByTestId("chat-row").first();
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(row.getByText(/4 messages/i)).toBeVisible();

    // Search.
    await page.getByTestId("chats-search").fill(codeword);
    await expect(page.getByTestId("chat-snippet")).toContainText(codeword, {
      timeout: 10_000,
    });
    await page.getByTestId("chats-search").clear();

    // Inline rename.
    await page.getByTestId("chat-rename-button").first().click();
    await page.getByTestId("chat-rename-input").fill("Renamed by e2e");
    await page.getByTestId("chat-rename-save").click();
    await expect(page.getByTestId("chat-title").first()).toHaveText(
      "Renamed by e2e",
      { timeout: 10_000 },
    );

    // Read-only transcript.
    await page.getByRole("button", { name: /transcript/i }).first().click();
    const transcript = page.getByTestId("chat-transcript");
    await expect(transcript).toBeVisible();
    await expect(transcript.getByText(new RegExp(codeword)).first()).toBeVisible();
    await expect(transcript.locator("textarea, input")).toHaveCount(0);

    // Delete.
    await page.getByTestId("chat-delete-button").first().click();
    await expect(page.getByTestId("chats-empty")).toBeVisible({ timeout: 10_000 });
  });
});
