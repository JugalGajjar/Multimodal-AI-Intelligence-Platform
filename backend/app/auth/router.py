from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.blocklist import is_disposable
from app.auth.deps import get_current_user
from app.auth.lockout import clear_failed_logins, is_locked_out, record_failed_login
from app.auth.models import User
from app.auth.schemas import (
    ChatSettingsResponse,
    ChatSettingsUpdate,
    ForgotPasswordRequest,
    GenericMessage,
    RegisterResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
    VerifyEmailRequest,
)
from app.auth.security import (
    create_access_token,
    generate_code,
    hash_password,
    verify_password,
)
from app.core.rate_limit import limiter
from app.db.session import get_db
from app.email.client import send_email
from app.email.templates import password_reset_email, verification_email

router = APIRouter(prefix="/auth", tags=["auth"])

DbDep = Annotated[AsyncSession, Depends(get_db)]
CurrentUserDep = Annotated[User, Depends(get_current_user)]

VERIFICATION_EXPIRY = timedelta(hours=24)
PASSWORD_RESET_EXPIRY = timedelta(hours=1)


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _set_verification_code(user: User) -> str:
    code = generate_code()
    user.verification_code_hash = hash_password(code)
    user.verification_code_expires_at = _utcnow() + VERIFICATION_EXPIRY
    return code


async def _set_password_reset_code(user: User) -> str:
    code = generate_code()
    user.password_reset_code_hash = hash_password(code)
    user.password_reset_code_expires_at = _utcnow() + PASSWORD_RESET_EXPIRY
    return code


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("5/hour")
async def register(request: Request, payload: UserRegister, db: DbDep) -> RegisterResponse:
    if is_disposable(str(payload.email)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Disposable email addresses are not allowed.",
        )

    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        is_verified=False,
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
    )
    code = await _set_verification_code(user)
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc
    await db.refresh(user)

    subject, body = verification_email(code)
    sent = await send_email(to=str(user.email), subject=subject, text=body)
    # No email provider configured → expose the code so tests/local dev can
    # still complete the flow. Prod always has a key, so this stays null.
    dev_code = None if sent else code
    return RegisterResponse(
        email=user.email,
        verification_sent=sent,
        dev_verification_code=dev_code,
    )


@router.post("/verify-email", response_model=TokenResponse)
@limiter.limit("10/15minute")
async def verify_email(request: Request, payload: VerifyEmailRequest, db: DbDep) -> TokenResponse:
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid code or email.",
        )

    if user.is_verified:
        # Idempotent: already verified just hands back a token.
        return TokenResponse(access_token=create_access_token(str(user.id)))

    if (
        user.verification_code_hash is None
        or user.verification_code_expires_at is None
        or user.verification_code_expires_at < _utcnow()
        or not verify_password(payload.code, user.verification_code_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid code or email.",
        )

    user.is_verified = True
    user.verification_code_hash = None
    user.verification_code_expires_at = None
    await db.commit()

    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.post("/resend-verification", response_model=GenericMessage)
@limiter.limit("3/hour")
async def resend_verification(
    request: Request, payload: ResendVerificationRequest, db: DbDep
) -> GenericMessage:
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    # Generic response either way — don't leak whether the email exists.
    if user is None or user.is_verified:
        return GenericMessage(message="If the account exists, a code was sent.")

    code = await _set_verification_code(user)
    await db.commit()
    subject, body = verification_email(code)
    await send_email(to=str(user.email), subject=subject, text=body)
    return GenericMessage(message="If the account exists, a code was sent.")


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/15minute")
async def login(request: Request, payload: UserLogin, db: DbDep) -> TokenResponse:
    # Per-account lockout — separate from the per-IP rate limit above.
    locked, retry_after = await is_locked_out(payload.email)
    if locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.hashed_password):
        await record_failed_login(payload.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Check your inbox for the code.",
        )

    await clear_failed_logins(payload.email)
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


@router.post("/forgot-password", response_model=GenericMessage)
@limiter.limit("3/hour")
async def forgot_password(
    request: Request, payload: ForgotPasswordRequest, db: DbDep
) -> GenericMessage:
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    # Always return the same shape so callers can't enumerate accounts.
    if user is not None and user.is_verified:
        code = await _set_password_reset_code(user)
        await db.commit()
        subject, body = password_reset_email(code)
        await send_email(to=str(user.email), subject=subject, text=body)
    return GenericMessage(message="If the account exists, a reset code was sent.")


@router.post("/reset-password", response_model=TokenResponse)
@limiter.limit("5/15minute")
async def reset_password(
    request: Request, payload: ResetPasswordRequest, db: DbDep
) -> TokenResponse:
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if user is None or not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid code or email.",
        )

    if (
        user.password_reset_code_hash is None
        or user.password_reset_code_expires_at is None
        or user.password_reset_code_expires_at < _utcnow()
        or not verify_password(payload.code, user.password_reset_code_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid code or email.",
        )

    user.hashed_password = hash_password(payload.new_password)
    user.password_reset_code_hash = None
    user.password_reset_code_expires_at = None
    await db.commit()

    return TokenResponse(access_token=create_access_token(str(user.id)))


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUserDep) -> User:
    return current_user


@router.get("/settings", response_model=ChatSettingsResponse)
async def get_settings(current_user: CurrentUserDep) -> User:
    return current_user


@router.patch("/settings", response_model=ChatSettingsResponse)
async def update_settings(
    payload: ChatSettingsUpdate,
    current_user: CurrentUserDep,
    db: DbDep,
) -> User:
    if payload.rag_mode is not None:
        current_user.rag_mode = payload.rag_mode
    if payload.web_max_results is not None:
        current_user.web_max_results = payload.web_max_results
    await db.commit()
    await db.refresh(current_user)
    return current_user
