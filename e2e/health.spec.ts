import { expect, test } from "@playwright/test";

test.describe("landing page + backend smoke", () => {
  test("renders the hero + brand mark", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: /chat with everything/i }),
    ).toBeVisible();
    // Brand wordmark in the top-left
    await expect(page.getByTestId("brand-mark").first()).toBeVisible();
  });

  test("backend /api/v1/health is reachable from the browser context", async ({
    page,
    request,
  }) => {
    const response = await request.get("http://localhost:8000/api/v1/health");
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body).toMatchObject({
      status: "ok",
      version: "0.1.0",
      environment: "development",
    });

    // CORS preflight from the page's origin
    await page.goto("/");
    const corsResp = await page.evaluate(async () => {
      const r = await fetch("http://localhost:8000/api/v1/health");
      return { status: r.status, body: await r.json() };
    });
    expect(corsResp.status).toBe(200);
    expect(corsResp.body.status).toBe("ok");
  });
});
