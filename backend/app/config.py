from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/workorders"
    redis_url: str = "redis://localhost:6379/0"
    llm_provider: Literal["gemini", "groq", "openai", "anthropic"] = "gemini"
    llm_api_key: str = ""
    cost_ceiling: float = 0.05
    max_steps: int = 8
    max_retries: int = 2
    retry_delay: int = 5

    class Config:
        env_file = ".env"


settings = Settings()
