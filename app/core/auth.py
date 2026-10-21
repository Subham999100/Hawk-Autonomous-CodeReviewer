
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import User
from app.db.session import get_db

security = HTTPBearer(auto_error=False)
_BCRYPT_SHA256_PREFIX = "bcrypt-sha256$"
_BCRYPT_MAX_PASSWORD_BYTES = 72


def _secret_value(value: Any) -> str:
    """Support both Pydantic SecretStr and ordinary strings."""
    if hasattr(value, "get_secret_value"):
        return value.get_secret_value()
    return str(value)


def _jwt_secret() -> str:
    secret = _secret_value(settings.auth_secret_key)
    if not secret:
        raise RuntimeError("Authentication signing secret is not configured")
    return secret


def get_password_hash(password: str) -> str:
    """Hash passwords with SHA-256 prehashing to avoid bcrypt's 72-byte limit."""
    password_digest = hashlib.sha256(password.encode("utf-8")).digest()
    hashed = bcrypt.hashpw(password_digest, bcrypt.gensalt())
    return f"{_BCRYPT_SHA256_PREFIX}{hashed.decode('utf-8')}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify new SHA-256-prehashed hashes and existing legacy bcrypt hashes."""
    try:
        if hashed_password.startswith(_BCRYPT_SHA256_PREFIX):
            stored_hash = hashed_password[len(_BCRYPT_SHA256_PREFIX):]
            password_bytes = hashlib.sha256(
                plain_password.encode("utf-8")
            ).digest()
            return bcrypt.checkpw(
                password_bytes,
                stored_hash.encode("utf-8"),
            )

        # Compatibility with hashes created by the previous implementation.
        legacy_password = plain_password.encode("utf-8")
        if len(legacy_password) > _BCRYPT_MAX_PASSWORD_BYTES:
            return False

        return bcrypt.checkpw(
            legacy_password,
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError, UnicodeError):
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed access token with an explicit expiry and issue time."""
    now = datetime.now(timezone.utc)
    expires_at = now + (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.auth_access_token_expire_minutes)
    )

    payload = data.copy()
    payload.update({"iat": now, "exp": expires_at})

    if settings.auth_issuer:
        payload["iss"] = settings.auth_issuer
    if settings.auth_audience:
        payload["aud"] = settings.auth_audience

    return jwt.encode(
        payload,
        _jwt_secret(),
        algorithm=settings.auth_algorithm,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """Validate signature, algorithm, expiry, and required identity claims."""
    options = {
        "require": ["exp", "iat", "sub"],
        "verify_aud": bool(settings.auth_audience),
        "verify_iss": bool(settings.auth_issuer),
    }

    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[settings.auth_algorithm],
            issuer=settings.auth_issuer or None,
            audience=settings.auth_audience or None,
            options=options,
        )

        if not isinstance(payload.get("sub"), str) or not payload["sub"].strip():
            raise jwt.InvalidTokenError("Invalid subject claim")

        return payload
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require a valid bearer token and an existing database user."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    user_id = payload["sub"]

    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require an authenticated user whose current database role is admin."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required",
        )

    return current_user
