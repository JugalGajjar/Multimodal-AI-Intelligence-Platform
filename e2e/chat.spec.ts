import { expect, test } from "@playwright/test";

import { registerAndSignIn } from "./auth-helpers";

async function setup(page: import("@playwright/test").Page) {
  await registerAndSignIn(page, "chat");
}

type ChatBody = {
  answer?: string;
  citations?: unknown[];
  entities_used?: unknown[];
  model?: string;
  used_context?: boolean;
  used_graph?: boolean;
  intent?: string;
  verification?: unknown;
};

function sseFromBody(body: ChatBody): string {
  const meta = {
    intent: body.intent ?? "chat",
    used_context: !!body.used_context,
    used_graph: !!body.used_graph,
    model: body.model ?? "",
    citations: body.citations ?? [],
    entities_used: body.entities_used ?? [],
  };
  const answer = body.answer ?? "";
  const tokens =
    answer.length === 0
      ? []
      : [answer.slice(0, Math.ceil(answer.length / 2)), answer.slice(Math.ceil(answer.length / 2))];
  const done = { verification: body.verification ?? null };
  let out = `event: meta\ndata: ${JSON.stringify(meta)}\n\n`;
  for (const t of tokens) out += `event: token\ndata: ${JSON.stringify({ text: t })}\n\n`;
  out += `event: done\ndata: ${JSON.stringify(done)}\n\n`;
  return out;
}

test.describe("frontend chat UI", () => {
  test("chat panel posts a query and renders answer + citations", async ({
    page,
  }) => {
    await page.route("**/api/v1/chat/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseFromBody({
          answer:
            "Embeddings are 384-dimensional vectors produced by BAAI/bge-small-en-v1.5 [1].",
          citations: [
            {
              chunk_id: "11111111-1111-1111-1111-111111111111",
              document_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
              chunk_index: 0,
              score: 0.83,
              text_preview: "Embeddings use BAAI/bge-small-en-v1.5 (384 dim).",
            },
          ],
          model: "openai/gpt-oss-20b:free",
          used_context: true,
        }),
      });
    });

    await setup(page);

    await page.getByLabel(/question/i).fill("What is the embedding dimension?");
    await page.getByRole("button", { name: /^send$/i }).click();

    await expect(page.getByTestId("chat-answer")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.getByText(/embeddings are 384-dimensional/i),
    ).toBeVisible();

    await expect(page.getByText("openai/gpt-oss-20b:free")).toBeVisible();
    await expect(page.getByText(/^used context$/i)).toBeVisible();

    await expect(page.getByTestId("citation-item")).toHaveCount(1);
    await expect(
      page.getByText(/Embeddings use BAAI\/bge-small-en-v1.5/i),
    ).toBeVisible();
  });

  test("chat panel surfaces a friendly message on 429 rate-limit", async ({
    page,
  }) => {
    await page.route("**/api/v1/chat/stream", async (route) => {
      await route.fulfill({
        status: 429,
        contentType: "application/json",
        body: JSON.stringify({ detail: "rate limited upstream" }),
      });
    });

    await setup(page);
    await page.getByLabel(/question/i).fill("anything");
    await page.getByRole("button", { name: /^send$/i }).click();

    await expect(page.getByText(/free-tier rate limit/i)).toBeVisible();
    await expect(page.getByTestId("chat-answer")).toBeHidden();
  });

  test("chat panel surfaces a friendly message on 503 missing-key", async ({
    page,
  }) => {
    await page.route("**/api/v1/chat/stream", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "OpenRouter API key not configured" }),
      });
    });

    await setup(page);
    await page.getByLabel(/question/i).fill("anything");
    await page.getByRole("button", { name: /^send$/i }).click();

    await expect(page.getByText(/not configured|key is missing/i)).toBeVisible();
  });
});

test.describe("inline knowledge graph in chat panel", () => {
  test("renders inline graph + 'used graph' badge + Explore-full-graph link", async ({
    page,
  }) => {
    await page.route("**/api/v1/chat/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseFromBody({
          answer: "Qdrant is the vector database used by the platform [1].",
          citations: [
            {
              chunk_id: "11111111-1111-1111-1111-111111111111",
              document_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
              chunk_index: 0,
              score: 0.81,
              text_preview: "Qdrant is the vector DB.",
            },
          ],
          entities_used: [
            {
              name: "Qdrant",
              type: "Technology",
              description: "open-source vector database",
              relations: [
                {
                  relation: "uses",
                  direction: "out",
                  other: "Cosine Distance",
                  other_type: "Concept",
                  other_description: "vector similarity metric",
                },
              ],
            },
            {
              name: "Cosine Distance",
              type: "Concept",
              description: "vector similarity metric",
              relations: [],
            },
          ],
          model: "openai/gpt-oss-20b",
          used_context: true,
          used_graph: true,
        }),
      });
    });

    await setup(page);
    await page.getByLabel(/question/i).fill("What does the platform use?");
    await page.getByRole("button", { name: /^send$/i }).click();

    await expect(page.getByTestId("chat-answer")).toBeVisible({
      timeout: 10_000,
    });
    await expect(page.getByText(/^used graph$/i)).toBeVisible();
    await expect(page.getByTestId("inline-graph")).toBeVisible();

    const link = page.getByTestId("inline-graph-explore-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/dashboard/graph");

    await expect(page.getByText(/Technology/).first()).toBeVisible();
  });

  test("inline graph is hidden when used_graph=false", async ({ page }) => {
    await page.route("**/api/v1/chat/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: sseFromBody({
          answer: "No graph context.",
          citations: [],
          entities_used: [],
          model: "openai/gpt-oss-20b",
          used_context: false,
          used_graph: false,
        }),
      });
    });

    await setup(page);
    await page.getByLabel(/question/i).fill("hi");
    await page.getByRole("button", { name: /^send$/i }).click();

    await expect(page.getByTestId("chat-answer")).toBeVisible();
    await expect(page.getByTestId("inline-graph")).toBeHidden();
    await expect(page.getByText(/^used graph$/i)).toBeHidden();
  });
});
