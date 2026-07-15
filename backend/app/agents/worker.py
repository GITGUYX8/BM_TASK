from app.agents.base import AgentNode
from app.core.models import AgentState


class WorkerNode(AgentNode):
    name = "worker"
    model_tier = "capable"

    async def run(self, state: AgentState) -> AgentState:
        return state
