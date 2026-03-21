"""
Redis-backed rate limiting with in-memory fallback.
"""
import hashlib
import logging
import time
from collections import defaultdict
from typing import Optional

from fastapi import Request
from redis.asyncio import Redis, from_url

from ..config import settings
from .auth import peek_token_subject

logger = logging.getLogger(__name__)


class RateLimiter:
    """Per-minute rate limiter keyed by device, JWT subject, or API key."""

    def __init__(self):
        self._counts: dict[tuple[str, int, str], int] = defaultdict(int)
        self._redis: Optional[Redis] = None

    async def connect(self) -> None:
        if settings.rate_limit_storage != "redis" or not settings.redis_url:
            return
        try:
            self._redis = from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
            await self._redis.ping()
            logger.info("Redis rate limiter enabled")
        except Exception as exc:
            logger.warning("Redis unavailable for rate limiting, falling back to memory: %s", exc)
            self._redis = None

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.close()

    def _hash_secret(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    def _device_identity(self, request: Request) -> str:
        parts = [part for part in request.url.path.split("/") if part]
        try:
            idx = parts.index("devices")
            return f"device:{parts[idx + 1]}"
        except Exception:
            token = request.headers.get("x-device-token")
            return f"device-token:{self._hash_secret(token)}" if token else "device:unknown"

    def _general_identity(self, request: Request) -> str:
        subject = peek_token_subject(request.headers.get("authorization"))
        if subject:
            return f"user:{subject}"
        api_key = request.headers.get("x-api-key")
        if api_key:
            return f"api-key:{self._hash_secret(api_key)}"
        client = request.client.host if request.client else "unknown"
        return f"ip:{client}"

    async def check(self, request: Request) -> tuple[bool, int, str]:
        if not settings.rate_limit_enabled:
            return True, 0, "disabled"

        path = request.url.path
        if path in {"/health", "/live", "/ready", "/metrics"}:
            return True, 0, "system"

        if path == "/api/v1/auth/change-password":
            category = "auth_change_password"
            identity = self._general_identity(request)
            limit = settings.rate_limit_change_password_per_minute
        elif path.startswith("/api/v1/esp/"):
            category = "esp"
            identity = self._device_identity(request)
            limit = settings.rate_limit_esp_per_minute
        else:
            category = "general"
            identity = self._general_identity(request)
            limit = settings.rate_limit_general_per_minute

        now_min = int(time.time() // 60)
        if self._redis is not None:
            key = f"rate:{category}:{identity}:{now_min}"
            current = await self._redis.incr(key)
            if current == 1:
                await self._redis.expire(key, 120)
            remaining = max(limit - current, 0)
            return current <= limit, remaining, category

        key = (identity, now_min, category)
        self._counts[key] += 1
        remaining = max(limit - self._counts[key], 0)

        old_min = now_min - 2
        stale_keys = [k for k in self._counts if k[1] < old_min]
        for stale in stale_keys:
            self._counts.pop(stale, None)

        return self._counts[key] <= limit, remaining, category
