import { expect, test } from "@playwright/test";

function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

// Next.js adds <div role="alert" id="__next-route-announcer__"> on every page,
// which makes getByRole("alert") ambiguous. Match visible error text directly.

test.describe("auth: register → dashboard → logout → login", () => {
  test("/dashboard redirects to /login when not authenticated", async ({
    page,
  }) => {
    await page.goto("/dashboard");
    await page.waitForURL("**/login");
    await expect(
      page.getByText(/sign in to your\s+MMAP\s+workspace/i),
    ).toBeVisible();
  });

  test("full happy path", async ({ page }) => {
    const email = uniqueEmail();
    const password = "abcdefgh";

    // --- Register ---
    await page.goto("/register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole("button", { name: /create account/i }).click();

    await page.waitForURL("**/dashboard");
    await expect(page.getByText(email)).toBeVisible();

    // --- Logout ---
    await page.getByRole("button", { name: /sign out/i }).click();
    await page.waitForURL("**/login");

    // --- Login with same credentials ---
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: /sign in/i }).click();

    await page.waitForURL("**/dashboard");
    await expect(page.getByText(email)).toBeVisible();
  });

  test("register rejects duplicate email", async ({ page }) => {
    const email = uniqueEmail();
    const password = "abcdefgh";

    await page.goto("/register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole("button", { name: /create account/i }).click();
    await page.waitForURL("**/dashboard");

    await page.getByRole("button", { name: /sign out/i }).click();
    await page.waitForURL("**/login");

    await page.goto("/register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByLabel(/confirm password/i).fill(password);
    await page.getByRole("button", { name: /create account/i }).click();

    await expect(page.getByText(/already registered/i)).toBeVisible();
    expect(page.url()).toContain("/register");
  });

  test("login rejects wrong password", async ({ page }) => {
    const email = uniqueEmail();

    await page.goto("/register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill("abcdefgh");
    await page.getByLabel(/confirm password/i).fill("abcdefgh");
    await page.getByRole("button", { name: /create account/i }).click();
    await page.waitForURL("**/dashboard");

    await page.getByRole("button", { name: /sign out/i }).click();
    await page.waitForURL("**/login");

    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill("WRONG-PASSWORD");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page.getByText(/invalid email or password/i)).toBeVisible();
    expect(page.url()).toContain("/login");
  });

  test("register form mismatched passwords is caught client-side (no API call)", async ({
    page,
  }) => {
    let apiHits = 0;
    await page.route("**/api/v1/auth/**", (route) => {
      apiHits++;
      route.continue();
    });

    await page.goto("/register");
    await page.getByLabel("Email").fill(uniqueEmail());
    await page.getByLabel("Password", { exact: true }).fill("abcdefgh");
    await page.getByLabel(/confirm password/i).fill("different");
    await page.getByRole("button", { name: /create account/i }).click();

    await expect(page.getByText(/passwords do not match/i)).toBeVisible();
    expect(apiHits).toBe(0);
  });
});
