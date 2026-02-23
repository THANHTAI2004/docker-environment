"""
Simple API key auth dependency for FastAPI.
"""
import hashlib

from fastapi import Header, HTTPException, status

from ..config import settings
from ..db import db


async def require_api_key(x_api_key: str | None = Header(default=None)):
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
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
