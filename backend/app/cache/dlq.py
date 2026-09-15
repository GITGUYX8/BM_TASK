"""Dead-letter queue for permanently failed orders.

When a Celery order task exhausts its retries, the order payload is pushed
onto the Redis list ``dlq:orders`` so operators can inspect/replay failures
instead of losing them. Reads never raise: Redis outages degrade to empty.
"""

import json
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import settings

DLQ_KEY = "dlq:orders"


class DeadLetterQueue:
    def __init__(self, redis_url: str = settings.redis_url, key: str = DLQ_KEY):
        self.redis_url = redis_url
        self.key = key

    async def push(self, entry: dict) -> None:
        payload = {
            **entry,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            redis = await aioredis.from_url(self.redis_url, decode_responses=True)
            try:
                await redis.rpush(self.key, json.dumps(payload))
            finally:
                await redis.aclose()
        except Exception:
            pass  # DLQ is best-effort; never mask the original failure

    async def list(self, limit: int = 50) -> list[dict]:
        try:
            redis = await aioredis.from_url(self.redis_url, decode_responses=True)
            try:
                raw = await redis.lrange(self.key, 0, limit - 1)
                return [json.loads(item) for item in raw]
            finally:
                await redis.aclose()
        except Exception:
            return []

    async def length(self) -> int:
        try:
            redis = await aioredis.from_url(self.redis_url, decode_responses=True)
            try:
                return int(await redis.llen(self.key) or 0)
            finally:
                await redis.aclose()
        except Exception:
            return 0
