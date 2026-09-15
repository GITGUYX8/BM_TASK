"""Phase 7 tests: done-key stream termination + per-process Redis client.

- The Celery task writes ``order:{id}:done`` exactly once per terminal run
  (success or retries-exhausted failure) and clears it on (re)start.
- The SSE loop ends on the done-key alone — no trace parsing.
- The shared Redis client connects once per process and reconnects
  after a fork (PID guard).

DB, Redis, and the agent graph are mocked; no services required.
"""

import asyncio
import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.cache.events import DONE_TTL_SECONDS, done_key
from app.core.models import AgentState, OrchestratorInput


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_redis_client():
    from app.cache import redis_client

    redis_client.reset_client()
    yield
    redis_client.reset_client()


def _mock_redis(**attrs):
    redis = AsyncMock()
    redis.get.side_effect = lambda key: attrs.get("get", {}).get(key)
    redis.hgetall.return_value = attrs.get("hgetall", {})
    return redis


def _patch_from_url(redis_mock):
    return patch("app.cache.redis_client.aioredis.from_url", return_value=redis_mock)


def _db_order(status="processing"):
    order = MagicMock()
    order.id = uuid.uuid4()
    order.title = "VPN down"
    order.description = "Users cannot connect"
    order.priority = "high"
    order.status = status
    order.cumulative_cost = Decimal("0.00")
    order.step_count = 0
    order.error_trace = None
    order.created_at = None
    order.updated_at = None
    return order


def _session_for(order):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = order
    scalars = MagicMock()
    scalars.all.return_value = []
    result.scalars.return_value = scalars
    session.execute.return_value = result
    return session


def _task(retries=0, max_retries=2):
    task = MagicMock()
    task.request.retries = retries
    task.max_retries = max_retries
    return task


# ── Done-key writes ───────────────────────────────────────────────


def test_task_sets_done_on_success():
    from app.tasks import process_order as task_module

    order_id = uuid.uuid4()
    session = _session_for(_db_order())
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session

    state = AgentState(
        order=OrchestratorInput(
            order_id=order_id,
            title="VPN down",
            description="Users cannot connect",
            priority="high",
        ),
        status="completed",
        cumulative_cost=Decimal("0.001"),
        current_step=4,
    )
    graph = MagicMock()
    graph.run = AsyncMock(return_value=state)
    redis = _mock_redis()

    with (
        patch.object(task_module, "async_session", return_value=session_cm),
        patch.object(task_module, "AgentGraph", return_value=graph),
        _patch_from_url(redis),
    ):
        out = _run(task_module._process_order(str(order_id), _task()))

    assert out == {"order_id": str(order_id), "status": "completed"}
    redis.setex.assert_any_call(
        done_key(str(order_id)), DONE_TTL_SECONDS, json.dumps({"status": "completed"})
    )
    # A fresh run clears any stale marker before doing work.
    redis.delete.assert_any_call(done_key(str(order_id)))


def test_task_sets_done_and_dlq_on_final_failure():
    from app.tasks import process_order as task_module

    order_id = uuid.uuid4()
    session = _session_for(_db_order())
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session

    graph = MagicMock()
    graph.run = AsyncMock(side_effect=RuntimeError("boom"))
    redis = _mock_redis()
    task = _task(retries=2, max_retries=2)
    task.retry.side_effect = RuntimeError("retry-exhausted")

    with (
        patch.object(task_module, "async_session", return_value=session_cm),
        patch.object(task_module, "AgentGraph", return_value=graph),
        _patch_from_url(redis),
    ):
        with pytest.raises(RuntimeError, match="retry-exhausted"):
            _run(task_module._process_order(str(order_id), task))

    redis.setex.assert_any_call(
        done_key(str(order_id)), DONE_TTL_SECONDS, json.dumps({"status": "failed"})
    )
    redis.rpush.assert_awaited_once()


def test_retryable_failure_sets_no_done_key():
    from app.tasks import process_order as task_module

    order_id = uuid.uuid4()
    session = _session_for(_db_order())
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session

    graph = MagicMock()
    graph.run = AsyncMock(side_effect=RuntimeError("boom"))
    redis = _mock_redis()
    task = _task(retries=0, max_retries=2)
    task.retry.side_effect = RuntimeError("retry-called")

    with (
        patch.object(task_module, "async_session", return_value=session_cm),
        patch.object(task_module, "AgentGraph", return_value=graph),
        _patch_from_url(redis),
    ):
        with pytest.raises(RuntimeError, match="retry-called"):
            _run(task_module._process_order(str(order_id), task))

    redis.setex.assert_not_called()
    redis.rpush.assert_not_called()


def test_retry_endpoint_clears_done_key():
    from app.api.orders import retry_order

    order_id = uuid.uuid4()
    failed = _db_order(status="failed")
    failed.id = order_id
    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = failed
    session = AsyncMock()
    session.execute.side_effect = [lookup, MagicMock()]
    redis = _mock_redis()

    with (
        patch("app.api.orders.process_order") as mock_task,
        patch("app.cache.redis_client.aioredis.from_url", return_value=redis),
    ):
        resp = _run(retry_order(order_id, session))

    mock_task.delay.assert_called_once_with(str(order_id))
    redis.delete.assert_any_call(done_key(str(order_id)))
    assert resp.order_id == order_id


# ── SSE loop reads the done-key ───────────────────────────────────


async def _collect_frames(response):
    return [frame async for frame in response.body_iterator]


def test_sse_ends_on_done_key_without_parsing_traces():
    from app.api.orders import stream_order

    order_id = uuid.uuid4()
    session = _session_for(_db_order(status="processing"))

    pubsub = AsyncMock()
    pubsub.get_message.side_effect = [
        {"type": "message", "data": "not-json{{{can't-parse"},
        None,
    ]
    sub_redis = AsyncMock()
    subscriber = MagicMock()
    subscriber.subscribe = AsyncMock(return_value=(pubsub, sub_redis))
    done_redis = _mock_redis(
        get={done_key(str(order_id)): json.dumps({"status": "failed"})}
    )

    with (
        patch("app.api.orders.TraceSubscriber", return_value=subscriber),
        patch("app.api.orders.get_client", return_value=done_redis),
    ):
        response = _run(stream_order(order_id, session))
        frames = _run(_collect_frames(response))

    text = "".join(frames)
    # The unparsable frame is forwarded verbatim — never inspected.
    assert "event: step\ndata: not-json{{{can't-parse" in text
    assert 'event: error\ndata: {"order_id": "%s", "status": "failed"}' % order_id in text
    assert text.count("event: done") == 1
    pubsub.unsubscribe.assert_awaited_once()
    sub_redis.aclose.assert_awaited_once()


def test_sse_waits_until_done_key_appears():
    from app.api.orders import stream_order

    order_id = uuid.uuid4()
    session = _session_for(_db_order(status="processing"))

    pubsub = AsyncMock()
    pubsub.get_message.side_effect = [None, None, None]
    sub_redis = AsyncMock()
    subscriber = MagicMock()
    subscriber.subscribe = AsyncMock(return_value=(pubsub, sub_redis))
    done_redis = _mock_redis()
    done_redis.get.side_effect = [None, None, json.dumps({"status": "completed"})]

    with (
        patch("app.api.orders.TraceSubscriber", return_value=subscriber),
        patch("app.api.orders.get_client", return_value=done_redis),
    ):
        response = _run(stream_order(order_id, session))
        frames = _run(_collect_frames(response))

    text = "".join(frames)
    assert "event: step" not in text
    assert "event: complete" in text
    assert done_redis.get.call_count == 3


# ── Per-process client ────────────────────────────────────────────


def test_client_reused_within_process():
    from app.cache import redis_client

    first, second = AsyncMock(), AsyncMock()
    with patch.object(
        redis_client.aioredis, "from_url", side_effect=[first, second]
    ) as from_url:
        assert _run(redis_client.get_client()) is first
        assert _run(redis_client.get_client()) is first
    assert from_url.call_count == 1


def test_client_reconnects_after_fork():
    from app.cache import redis_client

    first, second = AsyncMock(), AsyncMock()
    with (
        patch.object(redis_client.aioredis, "from_url", side_effect=[first, second]),
        patch("os.getpid", side_effect=[100, 100, 200, 200]),
    ):
        assert _run(redis_client.get_client()) is first
        assert _run(redis_client.get_client()) is first
        # PID changed → forked child reconnects instead of sharing the socket.
        assert _run(redis_client.get_client()) is second
