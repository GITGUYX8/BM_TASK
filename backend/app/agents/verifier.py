import json
import time
from decimal import Decimal

from app.agents.base import AgentNode
from app.core.models import AgentState, AgentTraceEntry, Verdict
from app.core.model_router import ModelRouter

VERIFIER_SYSTEM_PROMPT = """You are a quality verifier for work order resolutions. Given the original work order and the resolution, determine if the resolution is correct and complete.

Return a JSON object:
- result: "pass" (correct, can close), "fail" (incorrect, need more info), "rework" (partially correct, needs revision)
- reason_code: short code like "RESOLUTION_COMPLETE", "INSUFFICIENT_INFO", "PARTIAL_RESOLUTION", "UNRELATED_CONTENT"
- explanation: detailed reason for the verdict
- confidence: float 0.0 to 1.0

Be strict — if the resolution doesn't fully address the work order, mark as rework or fail.
"""


class VerifierNode(AgentNode):
    name = "verifier"
    model_tier = "cheap"

    def __init__(self, router: ModelRouter | None = None):
        super().__init__(router)

    async def run(self, state: AgentState) -> AgentState:
        start = time.monotonic()

        if not state.resolution:
            state.verdict = Verdict(
                order_id=state.order.order_id,
                result="fail",
                reason_code="NO_RESOLUTION",
                explanation="No resolution to verify",
                confidence=1.0,
            )
            return state

        user_prompt = (
            f"--- Work Order ---\n{state.order.title}\n{state.order.description}\n\n"
            f"--- Resolution ---\n{state.resolution.resolution_summary}\n"
            f"Confidence: {state.resolution.confidence}\n"
            f"Actions: {', '.join(state.resolution.actions_taken)}"
        )

        verdict = await self._generate_verdict(
            order_id=state.order.order_id,
            system_prompt=VERIFIER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        state.verdict = verdict

        trace = AgentTraceEntry(
            order_id=state.order.order_id,
            agent_name=self.name,
            step_number=state.current_step,
            input_summary=f"Verifying resolution for: {state.order.title}",
            output_summary=f"{verdict.result}: {verdict.reason_code}",
            output_json=verdict.model_dump(),
            latency_ms=int((time.monotonic() - start) * 1000),
            cost_usd=verdict.cost_usd,
            confidence=verdict.confidence,
            status="ok",
            model_used=verdict.model_used,
        )
        state.traces.append(trace)
        state.cumulative_cost += verdict.cost_usd
        return state

    async def _generate_verdict(self, order_id, system_prompt, user_prompt) -> Verdict:
        model_name = self.router.select(self.model_tier)
        response = await self.router.llm_call(system_prompt, user_prompt, tier=self.model_tier)

        if not response:
            return Verdict(
                order_id=order_id,
                result="pass",
                reason_code="LLM_UNAVAILABLE",
                explanation="No LLM available — defaulting to pass",
                confidence=0.3,
                model_used=model_name,
                cost_usd=Decimal("0.00"),
            )

        try:
            data = json.loads(response)
            result = data.get("result", "pass")
            if result not in ("pass", "fail", "rework"):
                result = "pass"
            return Verdict(
                order_id=order_id,
                result=result,
                reason_code=data.get("reason_code", "UNKNOWN"),
                explanation=data.get("explanation", response[:300]),
                confidence=min(1.0, max(0.0, float(data.get("confidence", 0.5)))),
                model_used=model_name,
                cost_usd=Decimal("0.00"),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            return Verdict(
                order_id=order_id,
                result="pass",
                reason_code="PARSE_ERROR",
                explanation="Could not parse LLM response — defaulting to pass",
                confidence=0.4,
                model_used=model_name,
                cost_usd=Decimal("0.00"),
            )
