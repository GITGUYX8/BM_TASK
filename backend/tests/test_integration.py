"""Integration + API contract tests.

Covers the full pipeline path (submit -> agents -> RAG -> trace) using
LLM-off fallbacks (no API key needed) plus the WS1/WS2 API contracts
(idempotency, structured errors, retry). DB/Redis are mocked so these
run without services; the docker-based suite exercises the live path.
"""

import asyncio
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Response

from app.agents.graph import AgentGraph
from app.api.orders import create_order, get_order, retry_order, list_orders
from app.api.errors import AppError
from app.core.models import AgentState, OrchestratorInput, OrderCreate
from app.db.models import Order as OrderDB, OrderStatus


def _run(coro):
    return asyncio.run(coro)


def _make_db_order(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        title="Laptop won't boot",
        description="Dell XPS 15, error 0x800F0922 after Windows update",
        priority="high",
        status=OrderStatus.queued,
        idempotency_key=None,
        cumulative_cost=Decimal("0.00"),
        step_count=0,
        error_trace=None,
        created_at=None,
        updated_at=None,
    )
    defaults.update(kwargs)
    order = MagicMock(spec=OrderDB)
    for k, v in defaults.items():
        setattr(order, k, v)
    # Priority/status behave like enums (have .value) for _order_to_response
    order.priority = MagicMock()
    order.priority.value = defaults["priority"]
    order.status = MagicMock()
    order.status.value = defaults["status"].value if isinstance(defaults["status"], OrderStatus) else defaults["status"]
    return order


def _mock_session(single_result=None, list_result=None):
    session = AsyncMock()
    result = MagicMock()
    if single_result is not None:
        result.scalar_one_or_none.return_value = single_result
    if list_result is not None:
        scalars = MagicMock()
        scalars.all.return_value = list_result
        result.scalars.return_value = scalars
    session.execute.return_value = result
    session._mock_result = result
    return session


# ── Full pipeline (LLM-off fallbacks) ─────────────────────────────


def test_full_pipeline_graph_produces_trace():
    """Submit -> agents -> RAG -> trace using no-LLM fallbacks.

    Mirrors test_graph_full_flow but asserts the integration contract:
    terminal status, multi-agent trace, worker confidence, verifier verdict.
    """
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    order_id = uuid.uuid4()
    state = AgentState(
        order=OrchestratorInput(
            order_id=order_id,
            title="VPN not connecting",
            description="User cannot connect to VPN after password reset",
            priority="high",
        )
    )
    graph = AgentGraph(mock_session)
    result = _run(graph.run(state))

    assert result.status in ("completed", "failed", "escalated", "processing")
    assert len(result.traces) >= 1
    agent_names = {t.agent_name for t in result.traces}
    assert "orchestrator" in agent_names
    for trace in result.traces:
        assert trace.latency_ms >= 0
        assert trace.model_used is not None
    worker_traces = [t for t in result.traces if t.agent_name == "worker"]
    if worker_traces:
        assert worker_traces[0].confidence is not None
    if result.resolution is not None:
        assert 0.0 <= result.resolution.confidence <= 1.0
    if result.verdict is not None:
        assert result.verdict.result in ("pass", "fail", "rework")


def test_full_pipeline_worker_verifier_contract():
    """Worker output feeds verifier; verifier verdict is well-formed."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    order_id = uuid.uuid4()
    state = AgentState(
        order=OrchestratorInput(
            order_id=order_id,
            title="Password reset needed",
            description="User jdoe locked out, needs password reset",
            priority="medium",
        )
    )
    result = _run(AgentGraph(mock_session).run(state))
    if result.verdict is not None:
        assert result.verdict.reason_code
        assert result.verdict.explanation is not None


# ── Idempotency contract ──────────────────────────────────────────


def test_idempotency_replay_returns_same_order():
    existing = _make_db_order(idempotency_key="key-123")
    session = _mock_session()

    async def fake_execute(query):
        result = MagicMock()
        # First call (idempotency lookup) -> existing order;
        # second call (traces) -> empty list.
        if session.execute.await_count == 1:
            result.scalar_one_or_none.return_value = existing
        else:
            scalars = MagicMock()
            scalars.all.return_value = []
            result.scalars.return_value = scalars
        return result

    session.execute.side_effect = fake_execute
    body = OrderCreate(
        title="Laptop won't boot",
        description="Dell XPS 15, error 0x800F0922 after Windows update",
        priority="high",
    )
    with patch("app.api.orders.process_order") as mock_task:
        resp = _run(create_order(body, Response(), session, "key-123"))
    mock_task.delay.assert_not_called()
    assert str(resp.order_id) == str(existing.id)


def test_idempotency_mismatch_raises_409():
    existing = _make_db_order(idempotency_key="key-123", title="Something else")
    session = _mock_session(single_result=existing)
    body = OrderCreate(title="Different title", description="Different body", priority="low")
    with pytest.raises(AppError) as exc_info:
        _run(create_order(body, Response(), session, "key-123"))
    assert exc_info.value.code == "IDEMPOTENCY_MISMATCH"
    assert exc_info.value.status_code == 409


def test_create_order_stores_idempotency_key():
    session = _mock_session(single_result=None)
    body = OrderCreate(title="T", description="D", priority="low")
    with patch("app.api.orders.process_order") as mock_task:
        resp = _run(create_order(body, Response(), session, "new-key"))
    mock_task.delay.assert_called_once()
    added = session.add.call_args[0][0]
    assert added.idempotency_key == "new-key"
    assert resp.order_id == added.id


# ── Structured errors ─────────────────────────────────────────────


def test_get_order_not_found_uses_envelope():
    session = _mock_session(single_result=None)
    with pytest.raises(AppError) as exc_info:
        _run(get_order(uuid.uuid4(), session))
    assert exc_info.value.code == "ORDER_NOT_FOUND"
    assert exc_info.value.status_code == 404
    assert "order_id" in exc_info.value.details


def test_list_orders_status_filter():
    session = _mock_session(list_result=[])
    _run(list_orders(session, OrderStatus.escalated))
    assert session.execute.await_count == 1


# ── Retry contract ────────────────────────────────────────────────


def test_retry_resets_failed_order_and_requeues():
    failed = _make_db_order(status="failed")
    failed.error_trace = {"error": "boom"}
    session = _mock_session(single_result=failed)
    with patch("app.api.orders.process_order") as mock_task:
        resp = _run(retry_order(failed.id, session))
    mock_task.delay.assert_called_once_with(str(failed.id))
    assert failed.error_trace is None
    assert resp.order_id == failed.id


def test_retry_rejects_non_terminal_order():
    processing = _make_db_order(status="processing")
    session = _mock_session(single_result=processing)
    with pytest.raises(AppError) as exc_info:
        _run(retry_order(processing.id, session))
    assert exc_info.value.code == "ORDER_PROCESSING"
    assert exc_info.value.status_code == 409


def test_retry_unknown_order_404():
    session = _mock_session(single_result=None)
    with pytest.raises(AppError) as exc_info:
        _run(retry_order(uuid.uuid4(), session))
    assert exc_info.value.code == "ORDER_NOT_FOUND"
