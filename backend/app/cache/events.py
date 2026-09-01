import json
import redis.asyncio as aioredis
from app.config import settings

CHANNEL_PREFIX = "order:%s:traces"


class TracePublisher:
    def __init__(self, redis_url: str = settings.redis_url):
        self.redis_url = redis_url

    async def publish(self, order_id: str, trace_data: dict):
        redis = await aioredis.from_url(self.redis_url, decode_responses=True)
        channel = CHANNEL_PREFIX % order_id
        await redis.publish(channel, json.dumps(trace_data))
        await redis.aclose()


class TraceSubscriber:
    def __init__(self, redis_url: str = settings.redis_url):
        self.redis_url = redis_url

    async def subscribe(self, order_id: str):
        redis = await aioredis.from_url(self.redis_url, decode_responses=True)
        channel = CHANNEL_PREFIX % order_id
        pubsub = redis.pubsub()
        await pubsub.subscribe(channel)
        return pubsub, redis
