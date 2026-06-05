import { expect, test } from "@playwright/test";

// Next.js adds <div role="alert" id="__next-route-announcer__"> on every page,
// which makes getByRole("alert") ambiguous. Match visible error text directly.

const STRONG = "StrongP@ss1";

function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

test.describe("auth: register → verify → dashboard → login", () => {
  test("/dashboard redirects to /login when not authenticated", async ({
    page,
  }) => {
    await page.goto("/dashboard");
    await page.waitForURL("**/login");
    await expect(
      page.getByText(/sign in to your\s+MMAP\s+workspace/i),
    ).toBeVisible();
  });

  test("register lands on the verify-email page with the email prefilled", async ({
    page,
  }) => {
    const email = uniqueEmail();

    await page.goto("/register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(STRONG);
    await page.getByLabel(/confirm password/i).fill(STRONG);
    await page.getByRole("button", { name: /create account/i }).click();

    await page.waitForURL(/\/verify-email/);
    await expect(page.getByLabel("Email")).toHaveValue(email);
  });

  test("verify with a valid code (mocked) lands on /dashboard", async ({
    page,
  }) => {
    const email = uniqueEmail();

    // Real register → verify-email page. Then mock the verify call so we don't
    // need access to the user's real code.
    await page.route("**/api/v1/auth/verify-email", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          access_token: "e2e-mock-token",
          token_type: "bearer",
        }),
      }),
    );
    await page.route("**/api/v1/auth/me", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "e2e-user",
          email,
          is_verified: true,
          created_at: "2026-01-01T00:00:00Z",
        }),
      }),
    );

    await page.goto(`/verify-email?email=${encodeURIComponent(email)}`);
    await page.getByLabel(/verification code/i).fill("ABCD1234");
    await page.getByRole("button", { name: /^verify$/i }).click();

    await page.waitForURL("**/dashboard");
    await expect(page.getByText(email)).toBeVisible();
  });

  test("register rejects duplicate email", async ({ page }) => {
    const email = uniqueEmail();

    await page.goto("/register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(STRONG);
    await page.getByLabel(/confirm password/i).fill(STRONG);
    await page.getByRole("button", { name: /create account/i }).click();
    await page.waitForURL(/\/verify-email/);

    await page.goto("/register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(STRONG);
    await page.getByLabel(/confirm password/i).fill(STRONG);
    await page.getByRole("button", { name: /create account/i }).click();

    await expect(page.getByText(/already registered/i)).toBeVisible();
    expect(page.url()).toContain("/register");
  });

  test("login shows unverified banner when account isn't verified", async ({
    page,
  }) => {
    const email = uniqueEmail();

    // Register a real user — they stay unverified.
    await page.goto("/register");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password", { exact: true }).fill(STRONG);
    await page.getByLabel(/confirm password/i).fill(STRONG);
    await page.getByRole("button", { name: /create account/i }).click();
    await page.waitForURL(/\/verify-email/);

    // Try to log in directly — backend should 403.
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(STRONG);
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page.getByText(/isn(’|')t verified/i)).toBeVisible();
    expect(page.url()).toContain("/login");
  });

  test("register form rejects weak passwords client-side", async ({ page }) => {
    let apiHits = 0;
    await page.route("**/api/v1/auth/**", (route) => {
      apiHits++;
      route.continue();
    });

    await page.goto("/register");
    await page.getByLabel("Email").fill(uniqueEmail());
    await page.getByLabel("Password", { exact: true }).fill("abcdefgh");
    await page.getByLabel(/confirm password/i).fill("abcdefgh");
    await page.getByRole("button", { name: /create account/i }).click();

    await expect(page.getByText(/password needs/i)).toBeVisible();
    expect(apiHits).toBe(0);
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
    await page.getByLabel("Password", { exact: true }).fill(STRONG);
    await page.getByLabel(/confirm password/i).fill(`${STRONG}x`);
    await page.getByRole("button", { name: /create account/i }).click();

    await expect(page.getByText(/passwords do not match/i)).toBeVisible();
    expect(apiHits).toBe(0);
  });

  test("forgot-password navigates to reset-password with email prefilled", async ({
    page,
  }) => {
    const email = uniqueEmail();

    await page.goto("/forgot-password");
    await page.getByLabel("Email").fill(email);
    await page.getByRole("button", { name: /send code/i }).click();

    await page.waitForURL(/\/reset-password/);
    await expect(page.getByLabel("Email")).toHaveValue(email);
  });
});
