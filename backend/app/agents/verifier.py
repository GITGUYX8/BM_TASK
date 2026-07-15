from app.agents.base import AgentNode
from app.core.models import AgentState


class VerifierNode(AgentNode):
    name = "verifier"
    model_tier = "cheap"

    async def run(self, state: AgentState) -> AgentState:
        return state
