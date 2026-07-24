import asyncio
from decimal import Decimal
from uuid import uuid4

from app.agents.orchestrator import OrchestratorNode
from app.agents.worker import WorkerNode
from app.agents.verifier import VerifierNode
from app.core.models import (
    AgentState,
    OrchestratorInput,
    RetrievedChunk,
    Resolution,
    Verdict,
)


def _run(coro):
    return asyncio.run(coro)


def _state(**kwargs):
    defaults = dict(
        order=OrchestratorInput(
            order_id=uuid4(),
            title="VPN not connecting",
            description="User cannot connect to VPN after password reset",
            priority="high",
        )
    )
    defaults.update(kwargs)
    return AgentState(**defaults)


# ── Orchestrator ─────────────────────────────────────────────────


def test_orchestrator_retrieve_on_fresh_state():
    result = _run(OrchestratorNode().run(_state()))
    assert result.routing_key == "retrieve"


def test_orchestrator_complete_on_pass_verdict():
    s = _state(
        verdict=Verdict(
            order_id=uuid4(), result="pass", confidence=1.0,
            reason_code="RESOLUTION_COMPLETE", explanation="ok",
        )
    )
    result = _run(OrchestratorNode().run(s))
    assert result.routing_key == "complete"


def test_orchestrator_fail_on_max_retries():
    s = _state(
        rework_count=3,
        verdict=Verdict(
            order_id=uuid4(), result="rework", confidence=0.8,
            reason_code="PARTIAL_RESOLUTION", explanation="needs work",
        ),
    )
    result = _run(OrchestratorNode().run(s))
    assert result.routing_key == "fail"


def test_orchestrator_resolve_on_chunks_ready():
    s = _state(
        retrieved_chunks=[
            RetrievedChunk(document_title="VPN Guide", chunk_text="Reset VPN credentials")
        ],
    )
    result = _run(OrchestratorNode().run(s))
    assert result.routing_key == "resolve"


def test_orchestrator_verify_on_resolution_ready():
    s = _state(
        retrieved_chunks=[
            RetrievedChunk(document_title="VPN Guide", chunk_text="Reset VPN credentials")
        ],
        resolution=Resolution(
            order_id=uuid4(), resolution_summary="Reset password", confidence=0.9,
        ),
    )
    result = _run(OrchestratorNode().run(s))
    assert result.routing_key == "verify"


def test_orchestrator_escalate_on_error():
    s = _state(error="Something broke")
    result = _run(OrchestratorNode().run(s))
    assert result.routing_key == "escalate"


def test_orchestrator_trace_appended():
    result = _run(OrchestratorNode().run(_state()))
    assert len(result.traces) == 1
    assert result.traces[0].agent_name == "orchestrator"
    assert result.traces[0].step_number == 1


# ── Worker ──────────────────────────────────────────────────────


def test_worker_fallback_no_llm():
    s = _state(
        current_step=1,
        retrieved_chunks=[
            RetrievedChunk(document_title="Doc", chunk_text="Some knowledge")
        ],
    )
    result = _run(WorkerNode().run(s))
    assert result.resolution is not None
    assert result.resolution.confidence == 0.1
    assert "No LLM available" in result.resolution.resolution_summary


def test_worker_fallback_empty_chunks():
    s = _state(current_step=1)
    result = _run(WorkerNode().run(s))
    assert result.resolution is not None
    assert result.resolution.confidence == 0.1


def test_worker_trace_created():
    s = _state(
        current_step=1,
        retrieved_chunks=[
            RetrievedChunk(document_title="Doc", chunk_text="Some knowledge")
        ],
    )
    result = _run(WorkerNode().run(s))
    assert len(result.traces) == 1
    assert result.traces[0].agent_name == "worker"


# ── Verifier ────────────────────────────────────────────────────


def test_verifier_fail_on_no_resolution():
    result = _run(VerifierNode().run(_state()))
    assert result.verdict is not None
    assert result.verdict.result == "fail"
    assert result.verdict.reason_code == "NO_RESOLUTION"


def test_verifier_fallback_no_llm():
    s = _state(
        current_step=1,
        resolution=Resolution(
            order_id=uuid4(), resolution_summary="Test resolution", confidence=0.9,
        ),
    )
    result = _run(VerifierNode().run(s))
    assert result.verdict is not None
    assert result.verdict.result == "pass"
    assert result.verdict.reason_code == "LLM_UNAVAILABLE"


def test_verifier_trace_created():
    s = _state(
        current_step=1,
        resolution=Resolution(
            order_id=uuid4(), resolution_summary="Test resolution", confidence=0.9,
        ),
    )
    result = _run(VerifierNode().run(s))
    assert len(result.traces) == 1
    assert result.traces[0].agent_name == "verifier"


# ── Graph ───────────────────────────────────────────────────────


def test_graph_full_flow():
    from unittest.mock import AsyncMock, MagicMock
    from sqlalchemy import text as sa_text
    from app.agents.graph import AgentGraph

    mock_result = MagicMock()
    mock_result.fetchall.return_value = []

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    graph = AgentGraph(mock_session)
    result = _run(graph.run(_state()))
    assert len(result.traces) >= 1
    assert result.traces[0].agent_name == "orchestrator"
    result.routing_key in ("retrieve", "complete", "fail", "escalate")
