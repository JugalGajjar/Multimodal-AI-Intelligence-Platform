from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.auth.passwords import PasswordError, validate_password


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=32)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _check_password(self) -> "UserRegister":
        try:
            validate_password(self.password, email=str(self.email))
        except PasswordError as exc:
            raise ValueError(str(exc)) from exc
        return self


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    is_verified: bool
    first_name: str | None = None
    last_name: str | None = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class RegisterResponse(BaseModel):
    """`/register` returns this so the client can route the user to
    `/verify-email` with the right hint shown."""

    email: EmailStr
    verification_sent: bool
    message: str = "Check your email for a verification code."
    # Only populated in dev/test when no email provider is configured —
    # otherwise the code only goes out via Resend.
    dev_verification_code: str | None = None


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=8, max_length=8)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=8, max_length=8)
    new_password: str = Field(min_length=8, max_length=32)

    @model_validator(mode="after")
    def _check_password(self) -> "ResetPasswordRequest":
        try:
            validate_password(self.new_password, email=str(self.email))
        except PasswordError as exc:
            raise ValueError(str(exc)) from exc
        return self


class GenericMessage(BaseModel):
    message: str
