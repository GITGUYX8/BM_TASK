from app.agents.base import AgentNode
from app.core.models import AgentState


class RetrieverNode(AgentNode):
    name = "retriever"
    model_tier = "cheap"

    async def run(self, state: AgentState) -> AgentState:
        return state
