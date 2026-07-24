from abc import ABC, abstractmethod
from app.core.models import AgentState
from app.core.model_router import ModelRouter


class AgentNode(ABC):
    name: str = "base"
    model_tier: str = "cheap"

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    @abstractmethod
    async def run(self, state: AgentState) -> AgentState:
        raise NotImplementedError
