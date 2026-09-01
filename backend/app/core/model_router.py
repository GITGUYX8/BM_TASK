from decimal import Decimal
from app.config import settings
from app.cache.redis import LLMCache

MODEL_TIERS = {
    "cheap": {
        "gemini": "gemini-1.5-flash",
        "groq": "llama3-8b-8192",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-haiku",
    },
    "capable": {
        "gemini": "gemini-1.5-pro",
        "groq": "llama3-70b-8192",
        "openai": "gpt-4o",
        "anthropic": "claude-3-sonnet",
    },
}

MODEL_PRICING = {
    "gemini-1.5-flash": Decimal("0.00000015"),
    "gemini-1.5-pro": Decimal("0.00000125"),
    "llama3-8b-8192": Decimal("0.00000005"),
    "llama3-70b-8192": Decimal("0.00000059"),
    "gpt-4o-mini": Decimal("0.00000015"),
    "gpt-4o": Decimal("0.00000250"),
    "claude-3-haiku": Decimal("0.00000025"),
    "claude-3-sonnet": Decimal("0.00000300"),
}


class ModelRouter:
    def __init__(self, provider: str | None = None):
        self.provider = provider or settings.llm_provider
        self.cache = LLMCache()
        self.last_cache_hit: bool = False

    def select(self, tier: str) -> str:
        return MODEL_TIERS[tier][self.provider]

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> Decimal:
        rate = MODEL_PRICING.get(model, Decimal("0.0000005"))
        return rate * Decimal(input_tokens + output_tokens)

    def _count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    async def llm_call(self, system_prompt: str, user_message: str, tier: str = "cheap") -> str | None:
        if not settings.llm_api_key:
            return None

        model = self.select(tier)
        combined = system_prompt + "||" + user_message

        try:
            cached = await self.cache.get(model, combined, 0.0)
            if cached and "text" in cached:
                self.last_cache_hit = True
                return cached["text"]
        except Exception:
            pass

        self.last_cache_hit = False

        if self.provider == "gemini":
            text = await self._call_gemini(model, system_prompt, user_message)
        elif self.provider == "openai":
            text = await self._call_openai(model, system_prompt, user_message)
        elif self.provider == "anthropic":
            text = await self._call_anthropic(model, system_prompt, user_message)
        elif self.provider == "groq":
            text = await self._call_groq(model, system_prompt, user_message)
        else:
            return None

        if text:
            try:
                await self.cache.set(model, combined, 0.0, {"text": text})
            except Exception:
                pass

        return text

    async def _call_gemini(self, model: str, system_prompt: str, user_message: str) -> str | None:
        import httpx

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, params={"key": settings.llm_api_key}, json=payload)
            if resp.status_code != 200:
                return None
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return None
            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            metadata = data.get("usageMetadata", {})
            in_tok = metadata.get("promptTokenCount", self._count_tokens(system_prompt + user_message))
            out_tok = metadata.get("candidatesTokenCount", self._count_tokens(text))
            return text

    async def _call_openai(self, model: str, system_prompt: str, user_message: str) -> str | None:
        import httpx

        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _call_anthropic(self, model: str, system_prompt: str, user_message: str) -> str | None:
        import httpx

        url = "https://api.anthropic.com/v1/messages"
        headers = {"x-api-key": settings.llm_api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
            "max_tokens": 1024,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data["content"][0]["text"]

    async def _call_groq(self, model: str, system_prompt: str, user_message: str) -> str | None:
        import httpx

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {settings.llm_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_message}],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data["choices"][0]["message"]["content"]
