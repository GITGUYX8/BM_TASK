"""Token-bucket rate limiter for order submission.

Each client IP gets a bucket (capacity 30 tokens, refilling at 30/minute)
stored as a Redis hash. Exceeding the bucket raises the structured
``RATE_LIMITED`` (429) error with a ``retry_after_seconds`` hint.
Redis outages fail open: the request is allowed rather than blocking
traffic because the limiter is down.
"""

import time

from fastapi import Request

from app.api.errors import AppError, ERROR_CATALOG
from app.cache.redis_client import get_client
from app.config import settings

KEY_PREFIX = "ratelimit:"
BUCKET_CAPACITY = 30
REFILL_PER_SECOND = BUCKET_CAPACITY / 60.0


async def rate_limit(
    request: Request,
    capacity: int = BUCKET_CAPACITY,
    redis_url: str = settings.redis_url,
) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = KEY_PREFIX + client_ip
    try:
        redis = await get_client(redis_url)
        now = time.time()
        data = await redis.hgetall(key)
        tokens = float(data.get("tokens", capacity))
        updated = float(data.get("updated", now))
        tokens = min(capacity, tokens + (now - updated) * REFILL_PER_SECOND)
        if tokens < 1:
            retry_after = max(1, int((1 - tokens) / REFILL_PER_SECOND))
            status_code, message = ERROR_CATALOG["RATE_LIMITED"]
            raise AppError(
                code="RATE_LIMITED",
                message=message,
                details={"retry_after_seconds": retry_after},
                status_code=status_code,
            )
        await redis.hset(key, mapping={"tokens": tokens - 1, "updated": now})
        await redis.expire(key, 120)
    except AppError:
        raise
    except Exception:
        pass  # fail open when Redis is unavailable
