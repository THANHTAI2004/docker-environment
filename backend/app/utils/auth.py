"""
Authentication helpers for JWT, refresh-token sessions, API-key bootstrap, and device tokens.
"""
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt
from fastapi import Header, HTTPException, Request, status

from ..config import settings
from ..db import db
from ..observability import AUTH_REFRESH_TOTAL


def _matches_secret(provided: str | None, expected: str) -> bool:
    return bool(provided) and secrets.compare_digest(provided, expected)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _db_now() -> datetime:
    return datetime.utcnow()


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


def create_access_token(user: Dict[str, Any], session_id: str) -> tuple[str, datetime]:
    """Create a signed JWT for one authenticated user session."""
    issued_at = _utc_now()
    expires_at = issued_at + timedelta(minutes=settings.jwt_access_token_exp_minutes)
    payload = {
        "sub": user["user_id"],
        "role": user["role"],
        "sid": session_id,
        "jti": secrets.token_urlsafe(8),
        "token_type": "access",
        "exp": expires_at,
        "iat": issued_at,
    }
    return (
        jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm),
        expires_at,
    )


def decode_access_token(token: str) -> Dict[str, Any]:
    """Validate and decode an access JWT."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
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

    token_type = payload.get("token_type") or "access"
    if token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        )
    return payload


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


def peek_token_role(authorization: str | None) -> str | None:
    """Best-effort role extraction for logging and metrics labels."""
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
        return payload.get("role")
    except jwt.InvalidTokenError:
        return None


def generate_refresh_token() -> str:
    """Generate an opaque refresh token that can be rotated and revoked."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """Hash refresh tokens before storing them in MongoDB."""
    raw = f"{settings.refresh_token_secret}:{token}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _is_active_session(session: Dict[str, Any] | None) -> bool:
    if not session:
        return False
    if session.get("revoked_at") is not None:
        return False
    expires_at = session.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at <= _db_now():
        return False
    return True


async def issue_session_tokens(user: Dict[str, Any]) -> Dict[str, Any]:
    """Create a persisted session and return fresh access + refresh tokens."""
    session_id = secrets.token_urlsafe(18)
    refresh_token = generate_refresh_token()
    refresh_expires_at = _db_now() + timedelta(days=settings.jwt_refresh_token_exp_days)
    created = await db.create_auth_session(
        {
            "session_id": session_id,
            "user_id": user["user_id"],
            "role": user["role"],
            "refresh_token_hash": hash_refresh_token(refresh_token),
            "expires_at": refresh_expires_at,
        }
    )
    if not created:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create auth session",
        )

    access_token, expires_at = create_access_token(user, session_id)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "refresh_expires_at": refresh_expires_at.replace(tzinfo=timezone.utc).isoformat(),
        "session_id": session_id,
        "user_id": user["user_id"],
        "role": user["role"],
        "scopes": [user["role"]],
    }


async def rotate_refresh_session(refresh_token: str) -> Dict[str, Any]:
    """Rotate one refresh token and issue a new access token for the same session."""
    session = await db.get_auth_session_by_refresh_token_hash(hash_refresh_token(refresh_token))
    if not _is_active_session(session):
        AUTH_REFRESH_TOTAL.labels(outcome="invalid").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = await db.get_user_auth(session["user_id"])
    if not user or not user.get("is_active", True):
        AUTH_REFRESH_TOTAL.labels(outcome="inactive_user").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is inactive or not found",
        )

    new_refresh_token = generate_refresh_token()
    refresh_expires_at = _db_now() + timedelta(days=settings.jwt_refresh_token_exp_days)
    rotated = await db.rotate_auth_session(
        session_id=session["session_id"],
        current_refresh_token_hash=session["refresh_token_hash"],
        new_refresh_token_hash=hash_refresh_token(new_refresh_token),
        expires_at=refresh_expires_at,
    )
    if not rotated:
        AUTH_REFRESH_TOTAL.labels(outcome="invalid").inc()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    access_token, expires_at = create_access_token(user, session["session_id"])
    AUTH_REFRESH_TOTAL.labels(outcome="success").inc()
    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "refresh_expires_at": refresh_expires_at.replace(tzinfo=timezone.utc).isoformat(),
        "session_id": session["session_id"],
        "user_id": user["user_id"],
        "role": user["role"],
        "scopes": [user["role"]],
    }


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
    """Require a valid bearer token, user record, and active session."""
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
    session_id = payload.get("sid")
    if not user_id or not session_id:
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

    session = await db.get_auth_session(session_id)
    if not _is_active_session(session) or session.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or revoked",
        )

    user["auth_type"] = "jwt"
    user["session_id"] = session_id
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
    """Protect metrics behind an explicit enable flag, token, and allowlist."""
    if not settings.expose_metrics:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    client_host = request.client.host if request.client else None
    allowed_hosts = {
        item.strip()
        for item in settings.metrics_allow_ips.split(",")
        if item.strip()
    }

    if settings.metrics_token and _matches_secret(x_metrics_token, settings.metrics_token):
        if client_host in allowed_hosts:
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Metrics source IP not allowed",
        )

    if client_host in allowed_hosts:
        return

    if settings.metrics_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Metrics token required",
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Metrics available only from allowed internal IPs",
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
