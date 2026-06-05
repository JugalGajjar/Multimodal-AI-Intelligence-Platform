// Mirrors backend/app/auth/passwords.py — keep them in sync.

export const MIN_LEN = 8;
export const MAX_LEN = 32;

const FORBIDDEN_SUBSTRINGS = ["mmap", "multimodal"];

export type PasswordRule = {
  id: string;
  label: string;
  ok: boolean;
};

export function evaluatePassword(password: string, email = ""): PasswordRule[] {
  const lower = password.toLowerCase();
  const emailLower = email.toLowerCase();
  const localPart = emailLower.split("@")[0] ?? "";

  return [
    {
      id: "length",
      label: `${MIN_LEN}–${MAX_LEN} characters`,
      ok: password.length >= MIN_LEN && password.length <= MAX_LEN,
    },
    { id: "lower", label: "a lowercase letter", ok: /[a-z]/.test(password) },
    { id: "upper", label: "an uppercase letter", ok: /[A-Z]/.test(password) },
    { id: "digit", label: "a digit", ok: /\d/.test(password) },
    {
      id: "special",
      label: "a special character",
      ok: /[^A-Za-z0-9]/.test(password),
    },
    {
      id: "no-product",
      label: "no product name",
      ok: !FORBIDDEN_SUBSTRINGS.some((t) => lower.includes(t)),
    },
    {
      id: "no-email",
      label: "doesn't contain your email",
      ok:
        !email ||
        (!lower.includes(emailLower) &&
          !(localPart.length >= 3 && lower.includes(localPart))),
    },
  ];
}

export function firstPasswordError(
  password: string,
  email = "",
): string | null {
  const failing = evaluatePassword(password, email).find((r) => !r.ok);
  return failing ? `Password needs ${failing.label}.` : null;
}
