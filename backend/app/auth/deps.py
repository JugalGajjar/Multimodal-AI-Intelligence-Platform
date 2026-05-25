from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.security import decode_access_token
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=True)

_credentials_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise _credentials_exception from exc

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise _credentials_exception

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise _credentials_exception from exc

    user = await db.get(User, user_id)
    if user is None:
        raise _credentials_exception
    return user
