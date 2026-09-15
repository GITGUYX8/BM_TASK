"""Phase 5 tests: metrics, rate limiting, dead-letter queue, pagination.

All dependencies (DB, Redis) are mocked; no services required.
"""

import asyncio
import json
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.errors import AppError
from app.api.metrics import metrics
from app.api.orders import create_order, list_orders
from app.api.rate_limit import rate_limit
from app.cache.dlq import DeadLetterQueue
from app.core.models import OrderCreate


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_redis_client():
    # The client is cached per process: reset between tests for isolation.
    from app.cache import redis_client

    redis_client.reset_client()
    yield
    redis_client.reset_client()


def _mock_redis(**attrs):
    redis = AsyncMock()
    redis.hgetall.return_value = attrs.get("hgetall", {})
    redis.get.side_effect = lambda key: attrs.get("get", {}).get(key)
    llen_map = attrs.get("llen", {})

    async def _llen(key):
        return llen_map.get(key, 0)

    redis.llen.side_effect = _llen
    return redis


def _patch_redis(redis_mock):
    return patch("app.cache.redis_client.aioredis.from_url", return_value=redis_mock)


def _request(ip="1.2.3.4"):
    req = MagicMock()
    req.client.host = ip
    return req


# ── Rate limiting ─────────────────────────────────────────────────


def test_rate_limit_allows_first_request():
    redis = _mock_redis(hgetall={})
    with _patch_redis(redis):
        _run(rate_limit(_request()))
    redis.hset.assert_awaited_once()
    redis.expire.assert_awaited_once()


def test_rate_limit_rejects_empty_bucket():
    redis = _mock_redis(hgetall={"tokens": "0", "updated": str(time.time())})
    with _patch_redis(redis):
        with pytest.raises(AppError) as exc_info:
            _run(rate_limit(_request()))
    assert exc_info.value.code == "RATE_LIMITED"
    assert exc_info.value.status_code == 429
    assert "retry_after_seconds" in exc_info.value.details


def test_rate_limit_fails_open_without_redis():
    with patch("app.cache.redis_client.aioredis.from_url", side_effect=ConnectionError):
        _run(rate_limit(_request()))  # must not raise


def test_rate_limit_refills_over_time():
    old = time.time() - 120  # two minutes ago: full refill expected
    redis = _mock_redis(hgetall={"tokens": "0", "updated": str(old)})
    with _patch_redis(redis):
        _run(rate_limit(_request()))
    redis.hset.assert_awaited_once()


# ── Dead-letter queue ─────────────────────────────────────────────


def test_dlq_push_includes_order_and_timestamp():
    redis = _mock_redis()
    with _patch_redis(redis):
        _run(
            DeadLetterQueue().push(
                {"order_id": "abc", "title": "T", "error": "boom", "retries": 2}
            )
        )
    redis.rpush.assert_awaited_once()
    key, payload = redis.rpush.call_args[0]
    assert key == "dlq:orders"
    body = json.loads(payload)
    assert body["order_id"] == "abc"
    assert body["retries"] == 2
    assert "failed_at" in body


def test_dlq_degrades_gracefully():
    with patch("app.cache.redis_client.aioredis.from_url", side_effect=ConnectionError):
        _run(DeadLetterQueue().push({"order_id": "x"}))  # must not raise
        assert _run(DeadLetterQueue().length()) == 0
        assert _run(DeadLetterQueue().list()) == []


# ── Metrics ───────────────────────────────────────────────────────


def test_metrics_exposition_format():
    status_result = MagicMock()
    status_result.all.return_value = [("completed", 2), ("failed", 1)]
    traces_result = MagicMock()
    traces_result.scalar.return_value = 7
    cost_result = MagicMock()
    cost_result.scalar.return_value = Decimal("0.012")
    session = AsyncMock()
    session.execute.side_effect = [status_result, traces_result, cost_result]

    redis = _mock_redis(get={"stats:cache_hits": "10", "stats:cache_misses": "3"},
                        llen={"celery": 4, "dlq:orders": 1})
    with _patch_redis(redis):
        body = _run(metrics(session))

    assert 'workorders_by_status{status="completed"} 2' in body
    assert 'workorders_by_status{status="failed"} 1' in body
    assert "workorder_traces_total 7" in body
    assert "workorder_cost_usd_total 0.012" in body
    assert "llm_cache_hits_total 10" in body
    assert "llm_cache_misses_total 3" in body
    assert "celery_queue_length 4" in body
    assert "dlq_length 1" in body


def test_metrics_degrades_without_backends():
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("db down")
    with patch("app.cache.redis_client.aioredis.from_url", side_effect=ConnectionError):
        body = _run(metrics(session))
    assert "workorder_traces_total 0" in body
    assert "celery_queue_length 0" in body


# ── Pagination ────────────────────────────────────────────────────


def test_list_orders_pagination_forwards():
    scalars = MagicMock()
    scalars.all.return_value = []
    result = MagicMock()
    result.scalars.return_value = scalars
    session = AsyncMock()
    session.execute.return_value = result
    out = _run(list_orders(session, None, 10, 5))
    assert out == []
    assert session.execute.await_count == 1


def test_create_order_still_works_with_limiter_param():
    from fastapi import Response

    lookup = MagicMock()
    lookup.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute.return_value = lookup
    body = OrderCreate(title="T", description="D", priority="low")
    with patch("app.api.orders.process_order") as mock_task:
        resp = _run(create_order(body, Response(), session, None))
    mock_task.delay.assert_called_once()
    assert resp.title == "T"
