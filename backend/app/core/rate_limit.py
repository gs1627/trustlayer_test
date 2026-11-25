from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Callable
import math
import time

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.core.errors import AppAPIError


class SlidingWindowRateLimiter:
    """In-memory per-process sliding-window rate limiter.

    Multi-worker production deployments must replace or front this with a
    shared distributed store (e.g. Redis) for global rate enforcement.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    async def check_and_consume(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        async with self._lock:
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                oldest = bucket[0]
                retry_after = max(1, math.ceil((oldest + window_seconds) - now))
                return False, 0, retry_after
            bucket.append(now)
            remaining = max(0, limit - len(bucket))
            return True, remaining, 0

    def reset(self) -> None:
        self._events.clear()


class WebSocketConnectionTracker:
    """Tracks active per-call WebSocket connection counts cleanly within one worker."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._counts: dict[str, int] = defaultdict(int)

    async def acquire(self, key: str, *, max_connections: int) -> bool:
        async with self._lock:
            current = self._counts[key]
            if current >= max_connections:
                return False
            self._counts[key] = current + 1
            return True

    async def release(self, key: str) -> None:
        async with self._lock:
            current = self._counts.get(key, 0)
            if current <= 1:
                self._counts.pop(key, None)
            else:
                self._counts[key] = current - 1

    def reset(self) -> None:
        self._counts.clear()


_rate_limiter = SlidingWindowRateLimiter()
_ws_tracker = WebSocketConnectionTracker()


def get_rate_limiter() -> SlidingWindowRateLimiter:
    return _rate_limiter


def get_ws_connection_tracker() -> WebSocketConnectionTracker:
    return _ws_tracker


def reset_rate_limiters() -> None:
    _rate_limiter.reset()
    _ws_tracker.reset()


def extract_client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first_hop = forwarded.split(",", 1)[0].strip()
        if first_hop:
            return first_hop
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def rate_limit(bucket: str, limit_getter: Callable[[Settings], int]):
    """Build a FastAPI dependency enforcing configured per-window rate limits."""

    async def _enforce_rate_limit(
        request: Request,
        limiter: SlidingWindowRateLimiter = Depends(get_rate_limiter),
    ) -> None:
        settings = get_settings()
        if not settings.rate_limit_enabled:
            return
        limit = limit_getter(settings)
        window = settings.rate_limit_window_seconds
        client_id = extract_client_key(request)
        key = f"{bucket}:{client_id}"
        allowed, _, retry_after = await limiter.check_and_consume(
            key,
            limit=limit,
            window_seconds=window,
        )
        if not allowed:
            raise AppAPIError(
                status_code=429,
                code="rate_limit_exceeded",
                message=f"Rate limit exceeded for {bucket}",
                retryable=True,
                details={
                    "bucket": bucket,
                    "limit": limit,
                    "window_seconds": window,
                    "retry_after_seconds": retry_after,
                },
            )

    return _enforce_rate_limit
