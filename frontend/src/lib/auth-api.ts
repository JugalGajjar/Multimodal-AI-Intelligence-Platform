import { apiFetch } from "@/lib/api";

export type AuthUserApi = {
  id: string;
  email: string;
  created_at: string;
};

export type TokenResponseApi = {
  access_token: string;
  token_type: string;
};

export function registerUser(
  email: string,
  password: string,
): Promise<AuthUserApi> {
  return apiFetch<AuthUserApi>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function loginUser(
  email: string,
  password: string,
): Promise<TokenResponseApi> {
  return apiFetch<TokenResponseApi>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function fetchCurrentUser(token: string): Promise<AuthUserApi> {
  return apiFetch<AuthUserApi>("/api/v1/auth/me", { token });
}
