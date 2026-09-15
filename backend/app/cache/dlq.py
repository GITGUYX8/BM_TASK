"""Dead-letter queue for permanently failed orders.

When a Celery order task exhausts its retries, the order payload is pushed
onto the Redis list ``dlq:orders`` so operators can inspect/replay failures
instead of losing them. Reads never raise: Redis outages degrade to empty.
"""

import json
from datetime import datetime, timezone

from app.cache.redis_client import get_client
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
            redis = await get_client(self.redis_url)
            await redis.rpush(self.key, json.dumps(payload))
        except Exception:
            pass  # DLQ is best-effort; never mask the original failure

    async def list(self, limit: int = 50) -> list[dict]:
        try:
            redis = await get_client(self.redis_url)
            raw = await redis.lrange(self.key, 0, limit - 1)
            return [json.loads(item) for item in raw]
        except Exception:
            return []

    async def length(self) -> int:
        try:
            redis = await get_client(self.redis_url)
            return int(await redis.llen(self.key) or 0)
        except Exception:
            return 0
