import { expect, test } from "@playwright/test";

function uniqueEmail(): string {
  return `docs-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

const TINY_PDF = Buffer.from(
  [
    "%PDF-1.4",
    "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj",
    "2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj",
    "xref",
    "0 3",
    "0000000000 65535 f ",
    "0000000009 00000 n ",
    "0000000053 00000 n ",
    "trailer<</Size 3/Root 1 0 R>>",
    "startxref",
    "95",
    "%%EOF",
    "",
  ].join("\n"),
);

async function registerAndSignIn(page: import("@playwright/test").Page) {
  const email = uniqueEmail();
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("abcdefgh");
  await page.getByLabel(/confirm password/i).fill("abcdefgh");
  await page.getByRole("button", { name: /create account/i }).click();
  await page.waitForURL("**/dashboard");
  return email;
}

test.describe("document upload", () => {
  test("upload a PDF, see it in the list, delete it", async ({ page }) => {
    await registerAndSignIn(page);

    // Empty state on dashboard
    await expect(page.getByText(/no documents yet/i)).toBeVisible();

    // Upload
    await page
      .getByLabel("File", { exact: true })
      .setInputFiles({
        name: "phase21.pdf",
        mimeType: "application/pdf",
        buffer: TINY_PDF,
      });
    await page.getByRole("button", { name: /^upload$/i }).click();

    // Appears in list
    await expect(page.getByText("phase21.pdf")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/1 document\b/i)).toBeVisible();

    // Delete
    await page.getByRole("button", { name: /^delete$/i }).click();
    await expect(page.getByText(/no documents yet/i)).toBeVisible({
      timeout: 10_000,
    });
  });

  test("rejects unsupported file type with a visible error", async ({ page }) => {
    await registerAndSignIn(page);

    await page.getByLabel("File", { exact: true }).setInputFiles({
      name: "evil.exe",
      mimeType: "application/x-msdownload",
      buffer: Buffer.from([0, 1, 2, 3]),
    });
    await page.getByRole("button", { name: /^upload$/i }).click();

    await expect(page.getByText(/unsupported file type/i)).toBeVisible();
  });

  test("uploads from one account are isolated from another account", async ({
    browser,
  }) => {
    // User A uploads
    const ctxA = await browser.newContext();
    const pageA = await ctxA.newPage();
    await registerAndSignIn(pageA);
    await pageA.getByLabel("File", { exact: true }).setInputFiles({
      name: "secret-A.pdf",
      mimeType: "application/pdf",
      buffer: TINY_PDF,
    });
    await pageA.getByRole("button", { name: /^upload$/i }).click();
    await expect(pageA.getByText("secret-A.pdf")).toBeVisible({
      timeout: 10_000,
    });

    // User B in a fresh context shouldn't see User A's doc
    const ctxB = await browser.newContext();
    const pageB = await ctxB.newPage();
    await registerAndSignIn(pageB);
    await expect(pageB.getByText("secret-A.pdf")).toBeHidden();
    await expect(pageB.getByText(/no documents yet/i)).toBeVisible();

    await ctxA.close();
    await ctxB.close();
  });
});
