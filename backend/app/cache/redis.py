import json
import hashlib
import redis.asyncio as aioredis
from app.config import settings


class LLMCache:
    def __init__(self, redis_url: str = settings.redis_url):
        self.redis = None
        self.redis_url = redis_url

    async def ensure_connected(self):
        if self.redis is None:
            self.redis = await aioredis.from_url(self.redis_url, decode_responses=True)

    def _make_key(self, model: str, prompt: str, temperature: float) -> str:
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        return f"llm:{model}:{prompt_hash}:{temperature}"

    async def get(self, model: str, prompt: str, temperature: float) -> dict | None:
        await self.ensure_connected()
        key = self._make_key(model, prompt, temperature)
        data = await self.redis.get(key)
        if data:
            await self.redis.incr("stats:cache_hits")
            return json.loads(data)
        await self.redis.incr("stats:cache_misses")
        return None

    async def set(self, model: str, prompt: str, temperature: float, response: dict):
        await self.ensure_connected()
        key = self._make_key(model, prompt, temperature)
        await self.redis.setex(key, 3600, json.dumps(response))
