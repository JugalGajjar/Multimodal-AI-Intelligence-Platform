import { expect, test } from "@playwright/test";

function uniqueEmail(): string {
  return `ocr-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
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

test.describe("Phase 2.2 — OCR pipeline (worker)", () => {
  test("text/plain upload → status processed → text visible in UI", async ({
    page,
  }) => {
    await registerAndSignIn(page);

    const content =
      "Phase 2.2 OCR end-to-end. The quick brown fox jumps over the lazy dog.";

    await page.getByLabel("File", { exact: true }).setInputFiles({
      name: "phase22.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(content),
    });
    await page.getByRole("button", { name: /^upload$/i }).click();

    // Status transitions to "processed"
    const statusBadge = page
      .getByText("phase22.txt")
      .locator("..")
      .locator("..")
      .getByText("processed", { exact: true });
    await expect(statusBadge).toBeVisible({ timeout: 30_000 });

    // View text button is now enabled
    const viewBtn = page.getByRole("button", { name: /view text/i });
    await viewBtn.click();

    // Extracted text shows up
    await expect(page.getByText(content)).toBeVisible({ timeout: 5_000 });

    // Hide it again
    await page.getByRole("button", { name: /hide text/i }).click();
    await expect(page.getByText(content)).toBeHidden();
  });

  test("status badge polls and updates without page reload", async ({ page }) => {
    await registerAndSignIn(page);

    await page.getByLabel("File", { exact: true }).setInputFiles({
      name: "poll.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("polling test"),
    });
    await page.getByRole("button", { name: /^upload$/i }).click();

    // Initially the doc shows up as uploaded or processing
    const row = page
      .getByText("poll.txt")
      .locator("..")
      .locator("..");
    await expect(
      row.getByText(/^(uploaded|processing|processed)$/),
    ).toBeVisible();

    // Eventually flips to processed
    await expect(row.getByText("processed", { exact: true })).toBeVisible({
      timeout: 30_000,
    });
  });
});
