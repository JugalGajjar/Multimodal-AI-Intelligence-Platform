import { expect, test } from "@playwright/test";

test.describe("Phase 1 smoke — landing page + backend integration", () => {
  test("renders the app title", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: "Multimodal AI Intelligence Platform" }),
    ).toBeVisible();
  });

  test("health card fetches backend and shows ok / version / environment", async ({
    page,
  }) => {
    await page.goto("/");

    const card = page.getByText("Backend status").locator("..").locator("..");
    await expect(card).toBeVisible();

    await expect(page.getByText("ok")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("0.1.0")).toBeVisible();
    await expect(page.getByText("development")).toBeVisible();
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
