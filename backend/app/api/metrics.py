"""Prometheus metrics endpoint.

Exposes order/queue/cache health in Prometheus exposition format at
``GET /metrics`` (root-mounted, the conventional scrape path):

- ``workorders_by_status`` — orders per status (DB)
- ``workorder_traces_total`` — agent trace rows stored (DB)
- ``workorder_cost_usd_total`` — cumulative LLM spend across orders (DB)
- ``llm_cache_hits_total`` / ``llm_cache_misses_total`` — Redis counters
- ``celery_queue_length`` — pending Celery messages (Redis ``celery`` list)
- ``dlq_length`` — permanently failed orders awaiting review (Redis DLQ)

Every source degrades to 0 on failure so scraping never 500s.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.dlq import DLQ_KEY
from app.cache.redis_client import get_client
from app.config import settings
from app.db.models import AgentTrace as AgentTraceDB
from app.db.models import Order as OrderDB
from app.db.session import get_session

router = APIRouter()

CELERY_QUEUE_KEY = "celery"
CACHE_HITS_KEY = "stats:cache_hits"
CACHE_MISSES_KEY = "stats:cache_misses"


async def _redis_int(redis, key: str, use_llen: bool = False) -> int:
    try:
        value = await redis.llen(key) if use_llen else await redis.get(key)
        return int(value or 0)
    except Exception:
        return 0


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(session: AsyncSession = Depends(get_session)):
    try:
        status_rows = (
            await session.execute(
                select(OrderDB.status, func.count(OrderDB.id)).group_by(OrderDB.status)
            )
        ).all()
    except Exception:
        status_rows = []
    try:
        traces_total = (
            await session.execute(select(func.count(AgentTraceDB.id)))
        ).scalar() or 0
    except Exception:
        traces_total = 0
    try:
        cost_total = (
            await session.execute(
                select(func.coalesce(func.sum(OrderDB.cumulative_cost), 0))
            )
        ).scalar() or 0
    except Exception:
        cost_total = 0

    cache_hits = cache_misses = celery_depth = dlq_depth = 0
    try:
        redis = await get_client(settings.redis_url)
        cache_hits = await _redis_int(redis, CACHE_HITS_KEY)
        cache_misses = await _redis_int(redis, CACHE_MISSES_KEY)
        celery_depth = await _redis_int(redis, CELERY_QUEUE_KEY, use_llen=True)
        dlq_depth = await _redis_int(redis, DLQ_KEY, use_llen=True)
    except Exception:
        pass

    lines = [
        "# HELP workorders_by_status Orders per status.",
        "# TYPE workorders_by_status gauge",
    ]
    for status, count in status_rows:
        name = status.value if hasattr(status, "value") else status
        lines.append(f'workorders_by_status{{status="{name}"}} {count}')
    lines += [
        "# HELP workorder_traces_total Agent trace rows stored.",
        "# TYPE workorder_traces_total counter",
        f"workorder_traces_total {traces_total}",
        "# HELP workorder_cost_usd_total Cumulative LLM spend across orders (USD).",
        "# TYPE workorder_cost_usd_total counter",
        f"workorder_cost_usd_total {cost_total}",
        "# HELP llm_cache_hits_total LLM cache hits.",
        "# TYPE llm_cache_hits_total counter",
        f"llm_cache_hits_total {cache_hits}",
        "# HELP llm_cache_misses_total LLM cache misses.",
        "# TYPE llm_cache_misses_total counter",
        f"llm_cache_misses_total {cache_misses}",
        "# HELP celery_queue_length Pending Celery messages.",
        "# TYPE celery_queue_length gauge",
        f"celery_queue_length {celery_depth}",
        "# HELP dlq_length Permanently failed orders awaiting review.",
        "# TYPE dlq_length gauge",
        f"dlq_length {dlq_depth}",
    ]
    return "\n".join(lines) + "\n"
