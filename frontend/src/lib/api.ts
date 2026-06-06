export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type ApiFetchInit = RequestInit & { token?: string | null };

export async function apiFetch<T>(
  path: string,
  init: ApiFetchInit = {},
): Promise<T> {
  const { token, headers: callerHeaders, ...rest } = init;
  const url = `${API_BASE_URL}${path}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...((callerHeaders as Record<string, string> | undefined) ?? {}),
  };

  const response = await fetch(url, { ...rest, headers });

  if (!response.ok) {
    const text = await response.text();
    let body: unknown = text;
    try {
      body = JSON.parse(text);
    } catch {
      // leave body as raw text
    }

    // A 401 on a request that DID send a token means the session expired or
    // was invalidated. Clear the local store and bounce to /login so the user
    // doesn't get stuck on a page full of "Failed to load" cards.
    // A 401 without a token (e.g. login attempt with wrong password) is a
    // normal validation error and stays as the caller's responsibility.
    if (response.status === 401 && token && typeof window !== "undefined") {
      handleSessionExpired();
    }

    throw new ApiError(
      `Request failed: ${response.status} ${response.statusText}`,
      response.status,
      body,
    );
  }

  return (await response.json()) as T;
}

function handleSessionExpired(): void {
  try {
    // Dynamic import avoids any boot-time cycle between api.ts ↔ store/auth.
    import("@/store/auth").then(({ useAuthStore }) => {
      useAuthStore.getState().clearSession();
    });
  } catch {
    // store unavailable in this environment — skip the local cleanup
  }
  if (window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

export type HealthResponse = {
  status: string;
  version: string;
  environment: string;
};

export function fetchHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/api/v1/health");
}
