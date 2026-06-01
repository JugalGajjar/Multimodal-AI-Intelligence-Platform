import { expect, test } from "@playwright/test";

function uniqueEmail(): string {
  return `chat-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

async function registerAndSignIn(page: import("@playwright/test").Page) {
  const email = uniqueEmail();
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("abcdefgh");
  await page.getByLabel(/confirm password/i).fill("abcdefgh");
  await page.getByRole("button", { name: /create account/i }).click();
  await page.waitForURL("**/dashboard");
}

test.describe("frontend chat UI", () => {
  test("chat panel posts a query and renders answer + citations", async ({
    page,
  }) => {
    // Intercept the real chat endpoint so the test is deterministic
    // regardless of OpenRouter free-tier rate-limits.
    await page.route("**/api/v1/chat", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
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

    await registerAndSignIn(page);

    // Type a question + submit
    await page
      .getByLabel(/question/i)
      .fill("What is the embedding dimension?");
    await page.getByRole("button", { name: /^send$/i }).click();

    // Answer renders
    await expect(page.getByTestId("chat-answer")).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.getByText(/embeddings are 384-dimensional/i),
    ).toBeVisible();

    // Model + used-context badge
    await expect(page.getByText("openai/gpt-oss-20b:free")).toBeVisible();
    await expect(page.getByText(/^used context$/i)).toBeVisible();

    // Citation present
    await expect(page.getByTestId("citation-item")).toHaveCount(1);
    await expect(
      page.getByText(/Embeddings use BAAI\/bge-small-en-v1.5/i),
    ).toBeVisible();
  });

  test("chat panel surfaces a friendly message on 429 rate-limit", async ({
    page,
  }) => {
    await page.route("**/api/v1/chat", async (route) => {
      await route.fulfill({
        status: 429,
        contentType: "application/json",
        body: JSON.stringify({ detail: "rate limited upstream" }),
      });
    });

    await registerAndSignIn(page);
    await page.getByLabel(/question/i).fill("anything");
    await page.getByRole("button", { name: /^send$/i }).click();

    await expect(page.getByText(/free-tier rate limit/i)).toBeVisible();
    await expect(page.getByTestId("chat-answer")).toBeHidden();
  });

  test("chat panel surfaces a friendly message on 503 missing-key", async ({
    page,
  }) => {
    await page.route("**/api/v1/chat", async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "OpenRouter API key not configured" }),
      });
    });

    await registerAndSignIn(page);
    await page.getByLabel(/question/i).fill("anything");
    await page.getByRole("button", { name: /^send$/i }).click();

    await expect(
      page.getByText(/openrouter api key is missing/i),
    ).toBeVisible();
  });
});

test.describe("inline knowledge graph in chat panel", () => {
  test("renders inline graph + 'used graph' badge + Explore-full-graph link", async ({
    page,
  }) => {
    // Mock the chat endpoint with a graph-augmented response.
    await page.route("**/api/v1/chat", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer:
            "Qdrant is the vector database used by the platform [1].",
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

    await registerAndSignIn(page);
    await page.getByLabel(/question/i).fill("What does the platform use?");
    await page.getByRole("button", { name: /^send$/i }).click();

    // Answer renders
    await expect(page.getByTestId("chat-answer")).toBeVisible({
      timeout: 10_000,
    });

    // The used-graph badge appears
    await expect(page.getByText(/^used graph$/i)).toBeVisible();

    // Inline graph block is shown
    await expect(page.getByTestId("inline-graph")).toBeVisible();

    // Explore-full-graph link points at /dashboard/graph
    const link = page.getByTestId("inline-graph-explore-link");
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", "/dashboard/graph");

    // The legend appears (force-graph canvas is hard to assert in Playwright,
    // but the surrounding markup must render). Look for the type label.
    await expect(page.getByText(/Technology/).first()).toBeVisible();
  });

  test("inline graph is hidden when used_graph=false", async ({ page }) => {
    await page.route("**/api/v1/chat", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          answer: "No graph context.",
          citations: [],
          entities_used: [],
          model: "openai/gpt-oss-20b",
          used_context: false,
          used_graph: false,
        }),
      });
    });

    await registerAndSignIn(page);
    await page.getByLabel(/question/i).fill("hi");
    await page.getByRole("button", { name: /^send$/i }).click();

    await expect(page.getByTestId("chat-answer")).toBeVisible();
    await expect(page.getByTestId("inline-graph")).toBeHidden();
    await expect(page.getByText(/^used graph$/i)).toBeHidden();
  });
});
