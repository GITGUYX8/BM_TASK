import json
import time
from decimal import Decimal

from app.agents.base import AgentNode
from app.core.models import AgentState, AgentTraceEntry, Resolution
from app.core.model_router import ModelRouter

WORKER_SYSTEM_PROMPT = """You are a work order resolution specialist. Given a work order description and retrieved knowledge base chunks, generate a resolution.

Return a JSON object with these fields:
- resolution_summary: str (detailed step-by-step resolution)
- confidence: float (0.0 to 1.0, how confident you are in this resolution)
- actions_taken: list[str] (specific actions to resolve the issue)

Base your resolution on the provided chunks. If chunks are insufficient, state that clearly and lower your confidence.
"""


class WorkerNode(AgentNode):
    name = "worker"
    model_tier = "capable"

    def __init__(self, router: ModelRouter | None = None):
        super().__init__(router)

    async def run(self, state: AgentState) -> AgentState:
        start = time.monotonic()

        chunks_text = self._format_chunks(state.retrieved_chunks)
        user_prompt = f"Work order: {state.order.title}\n{state.order.description}\n\nRetrieved knowledge:\n{chunks_text}"

        resolution = await self._generate_resolution(
            order_id=state.order.order_id,
            system_prompt=WORKER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        state.resolution = resolution
        state.rework_count += 1

        trace = AgentTraceEntry(
            order_id=state.order.order_id,
            agent_name=self.name,
            step_number=state.current_step,
            input_summary=f"{state.order.title}: {state.order.description[:100]}",
            output_summary=resolution.resolution_summary[:200],
            output_json=resolution.model_dump(),
            latency_ms=int((time.monotonic() - start) * 1000),
            cost_usd=resolution.cost_usd,
            confidence=resolution.confidence,
            status="ok",
            model_used=resolution.model_used,
            cache_hit=False,
        )
        state.traces.append(trace)
        state.cumulative_cost += resolution.cost_usd
        return state

    def _format_chunks(self, chunks) -> str:
        if not chunks:
            return "No relevant documents found."
        lines = []
        for i, c in enumerate(chunks, 1):
            snippet = c.chunk_text[:300].replace("\n", " ")
            lines.append(f"[{i}] {c.document_title}: {snippet}")
        return "\n".join(lines)

    async def _generate_resolution(self, order_id, system_prompt, user_prompt) -> Resolution:
        model_name = self.router.select(self.model_tier)
        response = await self.router.llm_call(system_prompt, user_prompt, tier=self.model_tier)

        if not response:
            return self._fallback_resolution(order_id, user_prompt, model_name)

        try:
            data = json.loads(response)
            return Resolution(
                order_id=order_id,
                resolution_summary=data.get("resolution_summary", response[:500]),
                confidence=min(1.0, max(0.0, float(data.get("confidence", 0.5)))),
                actions_taken=data.get("actions_taken", []),
                model_used=model_name,
                cost_usd=Decimal("0.00"),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            return Resolution(
                order_id=order_id,
                resolution_summary=response[:500],
                confidence=0.5,
                actions_taken=["Review work order manually"],
                model_used=model_name,
                cost_usd=Decimal("0.00"),
            )

    def _fallback_resolution(self, order_id, user_prompt, model_name) -> Resolution:
        return Resolution(
            order_id=order_id,
            resolution_summary=f"No LLM available. Raw work order:\n{user_prompt[:500]}",
            confidence=0.1,
            actions_taken=["Manual review required — LLM unavailable"],
            model_used=model_name,
            cost_usd=Decimal("0.00"),
        )
