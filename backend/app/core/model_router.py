from decimal import Decimal

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
    def __init__(self, provider: str = "gemini"):
        self.provider = provider

    def select(self, tier: str) -> str:
        return MODEL_TIERS[tier][self.provider]

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> Decimal:
        rate = MODEL_PRICING.get(model, Decimal("0.0000005"))
        return rate * Decimal(input_tokens + output_tokens)
