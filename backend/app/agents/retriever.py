import time
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentNode
from app.core.models import AgentState, AgentTraceEntry
from app.core.model_router import ModelRouter
from app.rag.pipeline import retrieve as rag_retrieve
from app.rag.embedding import EmbeddingService


class RetrieverNode(AgentNode):
    name = "retriever"
    model_tier = "cheap"

    def __init__(
        self,
        session: AsyncSession,
        embedder: EmbeddingService | None = None,
        router: ModelRouter | None = None,
    ):
        super().__init__(router)
        self.session = session
        self.embedder = embedder or EmbeddingService()

    async def run(self, state: AgentState) -> AgentState:
        start = time.monotonic()
        description = state.order.description

        chunks = await rag_retrieve(
            session=self.session,
            description=description,
            embedder=self.embedder,
            llm_call=self.router.llm_call if self.router else None,
            top_k=3,
        )

        state.retrieved_chunks = chunks

        trace = AgentTraceEntry(
            order_id=state.order.order_id,
            agent_name=self.name,
            step_number=state.current_step,
            input_summary=description[:200],
            output_summary=f"Retrieved {len(chunks)} chunks",
            latency_ms=int((time.monotonic() - start) * 1000),
            cost_usd=Decimal("0.00"),
            status="ok",
        )
        state.traces.append(trace)
        return state
