import { expect, test } from "@playwright/test";

import { registerAndSignIn } from "./auth-helpers";

async function setup(page: import("@playwright/test").Page) {
  await registerAndSignIn(page, "emb");
}

test.describe("embeddings + chunk count", () => {
  test("uploaded text shows N chunks after processing", async ({ page }) => {
    await setup(page);

    // Long enough to produce multiple chunks (default chunk_size=500)
    const body =
      "The quick brown fox jumps over the lazy dog. ".repeat(40) + "End.";

    await page.getByLabel("File", { exact: true }).setInputFiles({
      name: "phase23.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(body),
    });
    await page.getByRole("button", { name: /^upload$/i }).click();

    const row = page.getByText("phase23.txt").locator("..").locator("..");
    await expect(
      row.getByText("processed", { exact: true }),
    ).toBeVisible({ timeout: 60_000 });

    // Chunk count appears, expected >= 2 with the body above
    await expect(row.getByText(/\d+ chunks?/i)).toBeVisible({
      timeout: 10_000,
    });
  });
});
