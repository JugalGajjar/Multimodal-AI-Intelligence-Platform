import type { Page } from "@playwright/test";

export const STRONG_PASSWORD = "StrongP@ss1";

export function uniqueEmail(prefix = "e2e"): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

const API = "http://localhost:8000/api/v1";

/** Register, verify (via the dev_verification_code), and seed the auth store
 *  with the resulting token so the next page.goto lands as a signed-in user.
 *  Tests use this when they don't care about the auth UI itself. */
export async function registerAndSignIn(
  page: Page,
  prefix = "e2e",
): Promise<string> {
  const email = uniqueEmail(prefix);

  const reg = await page.request.post(`${API}/auth/register`, {
    data: { email, password: STRONG_PASSWORD },
  });
  if (!reg.ok()) {
    throw new Error(`/register failed: ${reg.status()} ${await reg.text()}`);
  }
  const regBody = await reg.json();
  const code: string | null = regBody.dev_verification_code;
  if (!code) {
    throw new Error(
      "/register did not return dev_verification_code — backend has RESEND_API_KEY set?",
    );
  }

  const verify = await page.request.post(`${API}/auth/verify-email`, {
    data: { email, code },
  });
  if (!verify.ok()) {
    throw new Error(`/verify-email failed: ${verify.status()} ${await verify.text()}`);
  }
  const { access_token } = await verify.json();

  // Seed Zustand persist storage so the next navigation sees us as authed.
  await page.addInitScript(
    ({ token, email }) => {
      localStorage.setItem(
        "mmap-auth",
        JSON.stringify({
          state: {
            user: { id: "e2e-user", email, isVerified: true },
            token,
          },
          version: 0,
        }),
      );
    },
    { token: access_token, email },
  );
  await page.goto("/dashboard");
  return email;
}
