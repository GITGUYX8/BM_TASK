"""Trace streaming primitives: pub/sub for live steps, done-key for termination.

Two separate mechanisms, deliberately:

- ``order:{id}:traces`` channel — fan-out of each agent step as it happens.
- ``order:{id}:done`` key — the single authoritative fact "this order is
  over, with this final status", written once by the Celery task (success or
  final failure) with a 1h TTL. The SSE handler reads it on every poll tick
  instead of guessing termination by string-matching trace payloads.
  A retry clears the key so a stale ``failed`` marker from the previous run
  can never end the new run's stream early.
"""

import json

import redis.asyncio as aioredis

from app.cache.redis_client import get_client
from app.config import settings

CHANNEL_PREFIX = "order:%s:traces"
DONE_KEY_TEMPLATE = "order:%s:done"
DONE_TTL_SECONDS = 3600


def done_key(order_id: str) -> str:
    return DONE_KEY_TEMPLATE % order_id


class TracePublisher:
    def __init__(self, redis_url: str = settings.redis_url):
        self.redis_url = redis_url

    async def publish(self, order_id: str, trace_data: dict):
        redis = await get_client(self.redis_url)
        channel = CHANNEL_PREFIX % order_id
        await redis.publish(channel, json.dumps(trace_data))

    async def publish_done(self, order_id: str, status: str):
        """Record the authoritative terminal status. Best-effort by design."""
        try:
            redis = await get_client(self.redis_url)
            await redis.setex(
                done_key(order_id), DONE_TTL_SECONDS, json.dumps({"status": status})
            )
        except Exception:
            pass

    async def clear_done(self, order_id: str):
        """Remove a stale done marker (retry/requeue). Best-effort by design."""
        try:
            redis = await get_client(self.redis_url)
            await redis.delete(done_key(order_id))
        except Exception:
            pass


class TraceSubscriber:
    def __init__(self, redis_url: str = settings.redis_url):
        self.redis_url = redis_url

    async def subscribe(self, order_id: str):
        # Dedicated connection per stream (see redis_client docstring):
        # subscribed mode blocks regular commands, and this connection's
        # lifetime is the stream's lifetime — closed by the caller.
        redis = await aioredis.from_url(self.redis_url, decode_responses=True)
        channel = CHANNEL_PREFIX % order_id
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        return pubsub, redis
