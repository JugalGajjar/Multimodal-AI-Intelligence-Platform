"""Password complexity rules — used by /register and /reset-password."""

from __future__ import annotations

import re

MIN_LEN = 8
MAX_LEN = 32

_FORBIDDEN_SUBSTRINGS = ("mmap", "multimodal")

_LOWER = re.compile(r"[a-z]")
_UPPER = re.compile(r"[A-Z]")
_DIGIT = re.compile(r"\d")
_SPECIAL = re.compile(r"[^A-Za-z0-9]")


class PasswordError(ValueError):
    """Raised when a password fails any of the rules."""


def validate_password(password: str, *, email: str | None = None) -> None:
    """Raise PasswordError if `password` violates any rule.

    Context-aware: `email` is checked so the password can't contain it
    or its local-part.
    """
    if not (MIN_LEN <= len(password) <= MAX_LEN):
        raise PasswordError(f"Password must be between {MIN_LEN} and {MAX_LEN} characters.")
    if not _LOWER.search(password):
        raise PasswordError("Password must contain a lowercase letter.")
    if not _UPPER.search(password):
        raise PasswordError("Password must contain an uppercase letter.")
    if not _DIGIT.search(password):
        raise PasswordError("Password must contain a digit.")
    if not _SPECIAL.search(password):
        raise PasswordError("Password must contain a special character.")

    lower_pwd = password.lower()
    for term in _FORBIDDEN_SUBSTRINGS:
        if term in lower_pwd:
            raise PasswordError(f"Password must not contain '{term}'.")

    if email:
        local = email.split("@", 1)[0].lower()
        if email.lower() in lower_pwd or (len(local) >= 3 and local in lower_pwd):
            raise PasswordError("Password must not contain your email.")
