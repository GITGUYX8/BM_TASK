from abc import ABC, abstractmethod
from app.core.models import AgentState


class AgentNode(ABC):
    name: str = "base"
    model_tier: str = "cheap"

    @abstractmethod
    async def run(self, state: AgentState) -> AgentState:
        raise NotImplementedError
