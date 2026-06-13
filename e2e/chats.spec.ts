import { expect, test } from "@playwright/test";

import { registerAndSignIn } from "./auth-helpers";

/** Ask a question on the dashboard chat (RAG off → fast pure-knowledge
 *  answer, no documents needed) and wait for the turn to land. */
async function ask(page: import("@playwright/test").Page, q: string, nthTurn: number) {
  // RAG off keeps answers fast and avoids needing uploaded docs.
  const rag = page.getByTestId("toggle-rag");
  if ((await rag.getAttribute("aria-pressed")) === "true") {
    await rag.click();
  }
  await page.getByLabel("Question").fill(q);
  await page.getByRole("button", { name: /^send$/i }).click();
  await expect(page.getByTestId("chat-turn")).toHaveCount(nthTurn, {
    timeout: 60_000,
  });
}

test.describe("Chat history", () => {
  test("thread persists across navigation; history page CRUD + search", async ({
    page,
  }) => {
    test.slow(); // two live LLM turns
    await registerAndSignIn(page, "chats");

    const codeword = `zebra${Date.now()}`;

    // Two turns on the dashboard.
    await ask(page, `Remember the codeword ${codeword}. What is RAG?`, 1);
    await ask(page, "What does it stand for?", 2);

    // Client-side navigation away and back — thread intact.
    await page.getByTestId("nav-your-documents").click();
    await expect(page).toHaveURL(/\/dashboard\/documents/);
    await page.getByTestId("nav-dashboard").click();
    await expect(page.getByTestId("chat-turn")).toHaveCount(2);

    // Chats page via sidebar.
    await page.getByTestId("nav-chats").click();
    await expect(page).toHaveURL(/\/dashboard\/chats/);
    const row = page.getByTestId("chat-row").first();
    await expect(row).toBeVisible({ timeout: 15_000 });
    await expect(row.getByText(/4 messages/i)).toBeVisible();

    // Search by the codeword from turn 1.
    await page.getByTestId("chats-search").fill(codeword);
    await expect(page.getByTestId("chat-snippet")).toContainText(codeword, {
      timeout: 15_000,
    });
    await page.getByTestId("chats-search").clear();

    // Inline rename.
    await page.getByTestId("chat-rename-button").first().click();
    await page.getByTestId("chat-rename-input").fill("Renamed by e2e");
    await page.getByTestId("chat-rename-save").click();
    await expect(page.getByTestId("chat-title").first()).toHaveText(
      "Renamed by e2e",
      { timeout: 15_000 },
    );

    // Read-only transcript.
    await page.getByRole("button", { name: /transcript/i }).first().click();
    const transcript = page.getByTestId("chat-transcript");
    await expect(transcript).toBeVisible();
    // The model may echo the codeword in its answer, so use first().
    await expect(transcript.getByText(new RegExp(codeword)).first()).toBeVisible();
    await expect(transcript.locator("textarea, input")).toHaveCount(0);

    // Delete.
    await page.getByTestId("chat-delete-button").first().click();
    await expect(page.getByTestId("chats-empty")).toBeVisible({
      timeout: 15_000,
    });
  });
});
