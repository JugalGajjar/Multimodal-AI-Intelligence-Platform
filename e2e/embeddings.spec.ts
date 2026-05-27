import { expect, test } from "@playwright/test";

function uniqueEmail(): string {
  return `emb-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
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

test.describe("Phase 2.3 — embeddings + chunk count", () => {
  test("uploaded text shows N chunks after processing", async ({ page }) => {
    await registerAndSignIn(page);

    // Long enough to produce multiple chunks (default chunk_size=500)
    const body =
      "Phase 2.3 embeddings end-to-end. " +
      "The quick brown fox jumps over the lazy dog. ".repeat(40) +
      "End.";

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
