"""
Authentication helpers for JWT, API-key bootstrap, and device tokens.
"""
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from fastapi import Header, HTTPException, Request, status

from ..config import settings
from ..db import db


def _matches_secret(provided: str | None, expected: str) -> bool:
    return bool(provided) and secrets.compare_digest(provided, expected)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_password(password: str, salt: str | None = None) -> str:
    """Create a PBKDF2 password hash suitable for storage."""
    raw_salt = salt or secrets.token_hex(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        raw_salt.encode("utf-8"),
        310000,
    )
    digest = base64.b64encode(derived).decode("ascii")
    return f"pbkdf2_sha256$310000${raw_salt}${digest}"


def verify_password(password: str, encoded: str | None) -> bool:
    """Verify a password against the stored PBKDF2 representation."""
    if not encoded:
        return False
    try:
        algorithm, iterations, salt, digest = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        )
        candidate = base64.b64encode(derived).decode("ascii")
        return hmac.compare_digest(candidate, digest)
    except Exception:
        return False


def create_access_token(user: Dict[str, Any]) -> tuple[str, datetime]:
    """Create a signed JWT for one authenticated user."""
    expires_at = _utc_now() + timedelta(minutes=settings.jwt_access_token_exp_minutes)
    payload = {
        "sub": user["user_id"],
        "role": user["role"],
        "exp": expires_at,
        "iat": _utc_now(),
    }
    return (
        jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm),
        expires_at,
    )


def decode_access_token(token: str) -> Dict[str, Any]:
    """Validate and decode a JWT."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        ) from exc


def peek_token_subject(authorization: str | None) -> str | None:
    """Best-effort subject extraction for rate limiting and logging."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
        return payload.get("sub")
    except jwt.InvalidTokenError:
        return None


async def require_api_key(x_api_key: str | None = Header(default=None)):
    """Retained for backward compatibility on internal-only code paths."""
    if _matches_secret(x_api_key, settings.api_key):
        return
    if _matches_secret(x_api_key, settings.admin_api_key):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
    )


async def require_admin_api_key(x_api_key: str | None = Header(default=None)):
    """Allow admin bootstrap with the shared admin secret only."""
    if not settings.allow_admin_api_key_bootstrap:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin API key bootstrap is disabled",
        )
    if _matches_secret(x_api_key, settings.admin_api_key):
        return {
            "user_id": "system-admin",
            "role": "admin",
            "auth_type": "api_key",
            "is_active": True,
        }
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing admin API key",
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin API key required",
    )


async def require_current_user(authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    """Require a valid bearer token and resolve the backing user record."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        )

    user = await db.get_user_auth(user_id)
    if not user or not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is inactive or not found",
        )
    user["auth_type"] = "jwt"
    return user


async def require_admin_user(authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    """Require an admin JWT and disallow API-key fallback."""
    user = await require_current_user(authorization)
    if user.get("role") == "admin":
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin role required",
    )


async def require_bootstrap_admin_principal(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> Dict[str, Any]:
    """Allow either an admin JWT or the break-glass admin API key."""
    if authorization and authorization.startswith("Bearer "):
        return await require_admin_user(authorization)
    return await require_admin_api_key(x_api_key)


async def require_admin_principal(
    authorization: str | None = Header(default=None),
) -> Dict[str, Any]:
    """Backward-compatible admin dependency that now requires JWT only."""
    return await require_admin_user(authorization)


async def require_metrics_access(
    request: Request,
    x_metrics_token: str | None = Header(default=None),
) -> None:
    """Protect metrics behind an explicit enable flag and optional token."""
    if not settings.expose_metrics:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if settings.metrics_token:
        if _matches_secret(x_metrics_token, settings.metrics_token):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Metrics token required",
        )

    client_host = request.client.host if request.client else None
    if client_host in {"127.0.0.1", "::1", "localhost"}:
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Metrics available only from localhost or with token",
    )


def hash_device_token(token: str) -> str:
    """Derive stable hash for ESP device token validation."""
    raw = f"{settings.device_token_secret}:{token}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def require_device_token(device_id: str, x_device_token: str | None = Header(default=None)):
    """Validate ESP device token from request header."""
    if not x_device_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing device token",
        )

    token_hash = hash_device_token(x_device_token)
    device = await db.get_device_by_token_hash(device_id, token_hash)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid device token",
        )
    return device
