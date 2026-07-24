import time
from decimal import Decimal
from app.agents.base import AgentNode
from app.core.models import AgentState, AgentTraceEntry, OrchestratorOutput
from app.core.model_router import ModelRouter
from app.config import settings

ORCHESTRATOR_SYSTEM_PROMPT = """You are an orchestrator agent for a work order processing system. Given the current state of a work order, decide the next action.

Available actions:
- retrieve: fetch relevant knowledge base chunks for this work order
- resolve: generate a resolution using the retrieved chunks
- verify: check if the resolution is correct and complete
- complete: mark the order as done (all steps passed)
- escalate: hand off to a human operator (can't handle)
- fail: abort processing (too many failures)

Analyze the state and respond with a JSON object:
{"action": "...", "reason": "..."}
"""


class OrchestratorNode(AgentNode):
    name = "orchestrator"
    model_tier = "cheap"

    def __init__(self, router: ModelRouter | None = None):
        self.router = router or ModelRouter()

    async def run(self, state: AgentState) -> AgentState:
        start = time.monotonic()
        output = await self._decide(state)
        state.current_step += 1

        trace = AgentTraceEntry(
            order_id=state.order.order_id,
            agent_name=self.name,
            step_number=state.current_step,
            input_summary=f"status={state.status}, step={state.current_step}",
            output_summary=output.reason,
            output_json=output.model_dump(),
            latency_ms=int((time.monotonic() - start) * 1000),
            cost_usd=output.cumulative_cost,
            status="ok",
            model_used=self.router.select(self.model_tier),
        )
        state.traces.append(trace)
        state.cumulative_cost += output.cumulative_cost

        state.routing_key = output.action
        if output.action in ("complete", "fail", "escalate"):
            state.status = output.action
        return state

    async def _decide(self, state: AgentState) -> OrchestratorOutput:
        if state.error:
            return OrchestratorOutput(
                action="escalate", reason=f"Error encountered: {state.error}",
                cumulative_cost=Decimal("0"), step_count=state.current_step,
            )

        if state.verdict and state.verdict.result == "pass":
            return OrchestratorOutput(
                action="complete", reason="Verification passed, completing order",
                cumulative_cost=Decimal("0"), step_count=state.current_step,
            )

        if state.verdict and state.verdict.result == "rework":
            if state.rework_count >= settings.max_retries:
                return OrchestratorOutput(
                    action="fail", reason=f"Rework limit ({settings.max_retries}) exceeded",
                    cumulative_cost=Decimal("0"), step_count=state.current_step,
                )
            return OrchestratorOutput(
                action="resolve", reason="Resolution needs rework, regenerating",
                cumulative_cost=Decimal("0"), step_count=state.current_step,
            )

        if state.verdict and state.verdict.result == "fail":
            return OrchestratorOutput(
                action="retrieve", reason="Verification failed, retrieving more context",
                cumulative_cost=Decimal("0"), step_count=state.current_step,
            )

        if state.resolution and not state.verdict:
            return OrchestratorOutput(
                action="verify", reason="Resolution ready, verifying",
                cumulative_cost=Decimal("0"), step_count=state.current_step,
            )

        if state.retrieved_chunks and not state.resolution:
            return OrchestratorOutput(
                action="resolve", reason="Chunks retrieved, generating resolution",
                cumulative_cost=Decimal("0"), step_count=state.current_step,
            )

        if not state.retrieved_chunks:
            return OrchestratorOutput(
                action="retrieve", reason="No chunks yet, starting retrieval",
                cumulative_cost=Decimal("0"), step_count=state.current_step,
            )

        return OrchestratorOutput(
            action="escalate", reason="Orchestrator cannot determine next step",
            cumulative_cost=Decimal("0"), step_count=state.current_step,
        )
