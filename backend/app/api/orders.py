import json
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_session
from app.db.models import Order as OrderDB, AgentTrace as AgentTraceDB
from app.db.models import OrderStatus
from app.core.models import OrderCreate, OrderResponse, AgentTraceEntry
from app.tasks.process_order import process_order
from app.cache.events import TraceSubscriber

router = APIRouter()


@router.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(
    body: OrderCreate,
    session: AsyncSession = Depends(get_session),
):
    order_id = uuid.uuid4()

    db_order = OrderDB(
        id=order_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        status=OrderStatus.queued,
    )
    session.add(db_order)
    await session.commit()

    process_order.delay(str(order_id))

    return _order_to_response(db_order)


@router.get("/orders", response_model=list[OrderResponse])
async def list_orders(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(OrderDB).order_by(OrderDB.created_at.desc()).limit(50))
    orders = result.scalars().all()
    return [_order_to_response(o) for o in orders]


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(OrderDB).where(OrderDB.id == order_id))
    db_order = result.scalar_one_or_none()
    if not db_order:
        raise HTTPException(status_code=404, detail="Order not found")

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
        raise HTTPException(status_code=404, detail="Order not found")

    async def event_generator():
        subscriber = TraceSubscriber()
        pubsub, redis = await subscriber.subscribe(str(order_id))

        try:
            terminal = False
            while not terminal:
                msg = await pubsub.get_message(timeout=1.0)
                if msg and msg["type"] == "message":
                    yield f"data: {msg['data']}\n\n"
                    trace = json.loads(msg["data"])
                    if trace.get("agent_name") in ("orchestrator", "retriever", "worker", "verifier"):
                        status = trace.get("output_json", {}).get("action") or trace.get("status")
                        if status in ("complete", "fail", "escalate"):
                            terminal = True
                            break
                elif not msg and terminal:
                    break
        finally:
            await pubsub.unsubscribe()
            await redis.aclose()

        # Send done event
        yield f"event: done\ndata: {json.dumps({'order_id': str(order_id), 'status': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


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
