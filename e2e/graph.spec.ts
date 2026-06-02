import { expect, test } from "@playwright/test";

function uniqueEmail(): string {
  return `kg-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

const SAMPLE = {
  nodes: [
    {
      id: "Qdrant",
      name: "Qdrant",
      type: "Technology",
      description: "open-source vector DB",
      document_ids: ["doc-aaaa"],
    },
    {
      id: "Cosine Distance",
      name: "Cosine Distance",
      type: "Concept",
      description: "similarity metric",
      document_ids: ["doc-aaaa"],
    },
    {
      id: "Jugal Gajjar",
      name: "Jugal Gajjar",
      type: "Person",
      description: "author",
      document_ids: ["doc-aaaa"],
    },
  ],
  links: [
    { source: "Qdrant", target: "Cosine Distance", relation: "uses" },
    {
      source: "Jugal Gajjar",
      target: "Qdrant",
      relation: "builds with",
    },
  ],
  node_count: 3,
  link_count: 2,
};

async function registerAndSignIn(page: import("@playwright/test").Page) {
  const email = uniqueEmail();
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("abcdefgh");
  await page.getByLabel(/confirm password/i).fill("abcdefgh");
  await page.getByRole("button", { name: /create account/i }).click();
  await page.waitForURL("**/dashboard");
}

test.describe("/dashboard/graph full graph page", () => {
  test("renders entity + relationship counts and the graph", async ({
    page,
  }) => {
    await page.route("**/api/v1/graph/snapshot*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SAMPLE),
      });
    });

    await registerAndSignIn(page);
    await page.goto("/dashboard/graph");

    await expect(page.getByTestId("full-graph-view")).toBeVisible();
    await expect(page.getByTestId("kg-node-count")).toHaveText(/3 entities/);
    await expect(page.getByTestId("kg-link-count")).toHaveText(
      /2 relationships/,
    );
  });

  test("renders the empty-state when the user has no entities", async ({
    page,
  }) => {
    await page.route("**/api/v1/graph/snapshot*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          nodes: [],
          links: [],
          node_count: 0,
          link_count: 0,
        }),
      });
    });

    await registerAndSignIn(page);
    await page.goto("/dashboard/graph");

    await expect(page.getByTestId("kg-empty-full")).toBeVisible();
  });

  test("sidebar Dashboard link navigates back to /dashboard", async ({ page }) => {
    await page.route("**/api/v1/graph/snapshot*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SAMPLE),
      });
    });

    await registerAndSignIn(page);
    await page.goto("/dashboard/graph");

    await page.getByTestId("nav-dashboard").click();
    await page.waitForURL("**/dashboard");
    await expect(page.getByTestId("app-shell-main")).toBeVisible();
  });

  test("unauthenticated /dashboard/graph redirects to /login", async ({
    page,
  }) => {
    await page.goto("/dashboard/graph");
    await page.waitForURL("**/login");
    await expect(
      page.getByText(/sign in to your\s+MMAP\s+workspace/i),
    ).toBeVisible();
  });

  test("typing in the search box narrows the displayed entity badge", async ({
    page,
  }) => {
    await page.route("**/api/v1/graph/snapshot*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SAMPLE),
      });
    });

    await registerAndSignIn(page);
    await page.goto("/dashboard/graph");

    await page.getByTestId("kg-search").fill("cosine");
    await expect(page.getByText(/showing \d+ matching/i)).toBeVisible();
  });

  test("inline graph 'Explore full graph' link navigates here end-to-end", async ({
    page,
  }) => {
    await page.route("**/api/v1/chat/stream", async (route) => {
      const meta = {
        intent: "chat",
        used_context: false,
        used_graph: true,
        model: "openai/gpt-oss-20b",
        citations: [],
        entities_used: [
          {
            name: "Qdrant",
            type: "Technology",
            description: "vector DB",
            relations: [],
          },
        ],
      };
      const answer = "Qdrant is the vector database used by the platform.";
      const body =
        `event: meta\ndata: ${JSON.stringify(meta)}\n\n` +
        `event: token\ndata: ${JSON.stringify({ text: answer })}\n\n` +
        `event: done\ndata: ${JSON.stringify({ verification: null })}\n\n`;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body,
      });
    });
    await page.route("**/api/v1/graph/snapshot*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SAMPLE),
      });
    });

    await registerAndSignIn(page);
    await page.getByLabel(/question/i).fill("What does the platform use?");
    await page.getByRole("button", { name: /^send$/i }).click();
    await expect(page.getByTestId("inline-graph")).toBeVisible();

    await page.getByTestId("inline-graph-explore-link").click();
    await page.waitForURL("**/dashboard/graph");
    await expect(page.getByTestId("full-graph-view")).toBeVisible();
  });
});
