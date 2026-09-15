import json
import uuid
from decimal import Decimal
from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select

from app.db.session import get_session
from app.db.models import Order as OrderDB, AgentTrace as AgentTraceDB
from app.db.models import OrderStatus
from app.core.models import OrderCreate, OrderResponse, AgentTraceEntry
from app.tasks.process_order import process_order
from app.cache.events import TraceSubscriber
from app.api.errors import AppError, ERROR_CATALOG

router = APIRouter()


def _app_error(code: str, details: dict | None = None) -> AppError:
    status_code, message = ERROR_CATALOG.get(code, (500, "Unexpected internal error"))
    return AppError(code=code, message=message, details=details or {}, status_code=status_code)


@router.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(
    body: OrderCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    if idempotency_key:
        existing_result = await session.execute(
            select(OrderDB).where(OrderDB.idempotency_key == idempotency_key)
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            if (
                existing.title != body.title
                or existing.description != body.description
                or (existing.priority.value if hasattr(existing.priority, "value") else existing.priority) != body.priority
            ):
                raise _app_error("IDEMPOTENCY_MISMATCH", {"idempotency_key": idempotency_key})
            response.status_code = 200
            traces_result = await session.execute(
                select(AgentTraceDB)
                .where(AgentTraceDB.order_id == existing.id)
                .order_by(AgentTraceDB.step_number)
            )
            return _order_to_response(existing, traces_result.scalars().all())

    order_id = uuid.uuid4()

    db_order = OrderDB(
        id=order_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        status=OrderStatus.queued,
        idempotency_key=idempotency_key,
    )
    session.add(db_order)
    await session.commit()

    process_order.delay(str(order_id))

    response.status_code = 201
    return _order_to_response(db_order)


@router.get("/orders", response_model=list[OrderResponse])
async def list_orders(
    session: AsyncSession = Depends(get_session),
    status: OrderStatus | None = None,
):
    query = select(OrderDB).order_by(OrderDB.created_at.desc()).limit(50)
    if status is not None:
        query = select(OrderDB).where(OrderDB.status == status).order_by(OrderDB.created_at.desc()).limit(50)
    result = await session.execute(query)
    orders = result.scalars().all()
    return [_order_to_response(o) for o in orders]


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(OrderDB).where(OrderDB.id == order_id))
    db_order = result.scalar_one_or_none()
    if not db_order:
        raise _app_error("ORDER_NOT_FOUND", {"order_id": str(order_id)})

    traces_result = await session.execute(
        select(AgentTraceDB).where(AgentTraceDB.order_id == order_id).order_by(AgentTraceDB.step_number)
    )
    db_traces = traces_result.scalars().all()
    return _order_to_response(db_order, db_traces)


@router.get("/orders/{order_id}/stream")
async def stream_order(order_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(OrderDB).where(OrderDB.id == order_id))
    db_order = result.scalar_one_or_none()
    if not db_order:
        raise _app_error("ORDER_NOT_FOUND", {"order_id": str(order_id)})

    db_status = db_order.status.value if hasattr(db_order.status, "value") else db_order.status

    async def event_generator():
        # Order already terminal before SSE connected: replay completion immediately
        if db_status in ("completed", "failed", "escalated"):
            payload = json.dumps({"order_id": str(order_id), "status": db_status})
            if db_status in ("failed", "escalated"):
                yield f"event: error\ndata: {payload}\n\n"
            else:
                yield f"event: complete\ndata: {payload}\n\n"
            yield f"event: done\ndata: {payload}\n\n"
            return

        subscriber = TraceSubscriber()
        pubsub, redis = await subscriber.subscribe(str(order_id))
        terminal_status = "done"

        try:
            while True:
                msg = await pubsub.get_message(timeout=1.0)
                if msg and msg["type"] == "message":
                    raw = msg["data"]
                    yield f"event: step\ndata: {raw}\n\n"
                    try:
                        trace = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    action = (trace.get("output_json") or {}).get("action")
                    trace_status = trace.get("status")
                    if action in ("complete", "fail", "escalate") or trace_status in (
                        "failed",
                        "escalated",
                    ):
                        if action == "fail" or trace_status == "failed":
                            terminal_status = "failed"
                        elif action == "escalate" or trace_status == "escalated":
                            terminal_status = "escalated"
                        else:
                            terminal_status = "completed"
                        break
        finally:
            await pubsub.unsubscribe()
            await redis.aclose()

        # Terminal events: named (complete/error) per spec + legacy `done` alias
        payload = json.dumps({"order_id": str(order_id), "status": terminal_status})
        if terminal_status in ("failed", "escalated"):
            yield f"event: error\ndata: {payload}\n\n"
        else:
            yield f"event: complete\ndata: {payload}\n\n"
        yield f"event: done\ndata: {payload}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/orders/{order_id}/retry", response_model=OrderResponse, status_code=202)
async def retry_order(order_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(OrderDB).where(OrderDB.id == order_id))
    db_order = result.scalar_one_or_none()
    if not db_order:
        raise _app_error("ORDER_NOT_FOUND", {"order_id": str(order_id)})

    current_status = db_order.status.value if hasattr(db_order.status, "value") else db_order.status
    if current_status not in ("failed", "escalated"):
        raise _app_error("ORDER_PROCESSING", {"order_id": str(order_id), "status": current_status})

    await session.execute(delete(AgentTraceDB).where(AgentTraceDB.order_id == order_id))
    db_order.status = OrderStatus.queued
    db_order.cumulative_cost = Decimal("0.00")
    db_order.step_count = 0
    db_order.error_trace = None
    await session.commit()

    process_order.delay(str(order_id))
    return _order_to_response(db_order, [])


def _order_to_response(db_order: OrderDB, db_traces: list[AgentTraceDB] | None = None) -> OrderResponse:
    traces = []
    if db_traces:
        traces = [
            AgentTraceEntry(
                id=t.id,
                order_id=t.order_id,
                agent_name=t.agent_name,
                step_number=t.step_number,
                input_summary=t.input_summary or "",
                output_summary=t.output_summary or "",
                output_json=t.output_json,
                latency_ms=t.latency_ms,
                cost_usd=t.cost_usd,
                confidence=t.confidence,
                status=t.status.value if hasattr(t.status, "value") else t.status,
                model_used=t.model_used or "",
                cache_hit=t.cache_hit,
            )
            for t in db_traces
        ]

    return OrderResponse(
        order_id=db_order.id,
        title=db_order.title,
        description=db_order.description,
        priority=db_order.priority.value if hasattr(db_order.priority, "value") else db_order.priority,
        status=db_order.status.value if hasattr(db_order.status, "value") else db_order.status,
        cumulative_cost=db_order.cumulative_cost,
        step_count=db_order.step_count,
        traces=traces,
        error_trace=db_order.error_trace,
        created_at=str(db_order.created_at) if db_order.created_at else "",
        updated_at=str(db_order.updated_at) if db_order.updated_at else "",
    )
