"""Text bodies for the transactional emails. Plain-text only — no HTML yet."""

from __future__ import annotations

PRODUCT_NAME = "Multimodal AI Intelligence Platform"


def verification_email(code: str) -> tuple[str, str]:
    subject = f"Your {PRODUCT_NAME} verification code"
    body = (
        f"Welcome to {PRODUCT_NAME}.\n\n"
        f"Your verification code is: {code}\n\n"
        "It expires in 24 hours. Enter it on the verification page to "
        "activate your account.\n\n"
        "If you didn't sign up, you can ignore this email.\n"
    )
    return subject, body


def password_reset_email(code: str) -> tuple[str, str]:
    subject = f"{PRODUCT_NAME} — password reset code"
    body = (
        f"A password reset was requested for your {PRODUCT_NAME} account.\n\n"
        f"Your reset code is: {code}\n\n"
        "It expires in 1 hour and can only be used once. If you didn't "
        "request a reset, you can ignore this email.\n"
    )
    return subject, body
