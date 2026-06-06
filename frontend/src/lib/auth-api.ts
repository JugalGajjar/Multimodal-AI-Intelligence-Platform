import { apiFetch } from "@/lib/api";

export type AuthUserApi = {
  id: string;
  email: string;
  is_verified: boolean;
  first_name: string | null;
  last_name: string | null;
  created_at: string;
};

export type TokenResponseApi = {
  access_token: string;
  token_type: string;
};

export type RegisterResponseApi = {
  email: string;
  verification_sent: boolean;
  message: string;
};

export type GenericMessageApi = {
  message: string;
};

export function registerUser(
  email: string,
  password: string,
  firstName: string,
  lastName: string,
): Promise<RegisterResponseApi> {
  return apiFetch<RegisterResponseApi>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({
      email,
      password,
      first_name: firstName,
      last_name: lastName,
    }),
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

export function verifyEmail(
  email: string,
  code: string,
): Promise<TokenResponseApi> {
  return apiFetch<TokenResponseApi>("/api/v1/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  });
}

export function resendVerification(email: string): Promise<GenericMessageApi> {
  return apiFetch<GenericMessageApi>("/api/v1/auth/resend-verification", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function forgotPassword(email: string): Promise<GenericMessageApi> {
  return apiFetch<GenericMessageApi>("/api/v1/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function resetPassword(
  email: string,
  code: string,
  newPassword: string,
): Promise<TokenResponseApi> {
  return apiFetch<TokenResponseApi>("/api/v1/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ email, code, new_password: newPassword }),
  });
}

export function fetchCurrentUser(token: string): Promise<AuthUserApi> {
  return apiFetch<AuthUserApi>("/api/v1/auth/me", { token });
}
