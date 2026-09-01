from collections.abc import Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import OrchestratorNode
from app.agents.retriever import RetrieverNode
from app.agents.worker import WorkerNode
from app.agents.verifier import VerifierNode
from app.core.models import AgentState, AgentTraceEntry
from app.core.model_router import ModelRouter
from app.core.cost_tracker import CostTracker
from app.config import settings


class AgentGraph:
    def __init__(
        self,
        session: AsyncSession,
        router: ModelRouter | None = None,
        on_trace: Callable[[AgentTraceEntry], Awaitable[None]] | None = None,
    ):
        self.router = router or ModelRouter()
        self.orchestrator = OrchestratorNode(self.router)
        self.retriever = RetrieverNode(session, router=self.router)
        self.worker = WorkerNode(self.router)
        self.verifier = VerifierNode(self.router)
        self.cost_tracker = CostTracker(ceiling=settings.cost_ceiling)
        self.on_trace = on_trace

    async def _emit_trace(self, state: AgentState):
        if self.on_trace and state.traces:
            await self.on_trace(state.traces[-1])

    async def run(self, state: AgentState) -> AgentState:
        while state.status == "processing":
            state = await self.orchestrator.run(state)
            await self._emit_trace(state)
            key = state.routing_key

            if state.forced_cheap or self.cost_tracker.forced_cheap:
                self.worker.model_tier = "cheap"
                self.verifier.model_tier = "cheap"
                state.forced_cheap = True

            if key == "retrieve":
                state = await self.retriever.run(state)
                await self._emit_trace(state)
            elif key == "resolve":
                state = await self.worker.run(state)
                await self._emit_trace(state)
            elif key == "verify":
                state = await self.verifier.run(state)
                await self._emit_trace(state)
            elif key in ("complete", "fail", "escalate"):
                break
            else:
                state.status = "failed"
                state.error = f"Unknown routing key: {key}"
                break

            if state.traces:
                self.cost_tracker.add_cost(state.traces[-1].cost_usd)
                if self.cost_tracker.forced_cheap:
                    state.forced_cheap = True

            if state.current_step >= settings.max_steps:
                state.status = "failed"
                state.error = f"Max steps ({settings.max_steps}) exceeded"
                break

        return state
