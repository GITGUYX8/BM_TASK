from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import OrchestratorNode
from app.agents.retriever import RetrieverNode
from app.agents.worker import WorkerNode
from app.agents.verifier import VerifierNode
from app.core.models import AgentState
from app.core.model_router import ModelRouter
from app.config import settings


class AgentGraph:
    def __init__(self, session: AsyncSession, router: ModelRouter | None = None):
        self.router = router or ModelRouter()
        self.orchestrator = OrchestratorNode(self.router)
        self.retriever = RetrieverNode(session, router=self.router)
        self.worker = WorkerNode(self.router)
        self.verifier = VerifierNode(self.router)

    async def run(self, state: AgentState) -> AgentState:
        while state.status == "processing":
            state = await self.orchestrator.run(state)
            key = state.routing_key

            if key == "retrieve":
                state = await self.retriever.run(state)
            elif key == "resolve":
                state = await self.worker.run(state)
            elif key == "verify":
                state = await self.verifier.run(state)
            elif key in ("complete", "fail", "escalate"):
                break
            else:
                state.status = "failed"
                state.error = f"Unknown routing key: {key}"
                break

            if state.current_step >= settings.max_steps:
                state.status = "failed"
                state.error = f"Max steps ({settings.max_steps}) exceeded"
                break

        return state
