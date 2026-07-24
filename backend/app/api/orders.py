import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_session
from app.db.models import Order as OrderDB, AgentTrace as AgentTraceDB
from app.db.models import OrderStatus
from app.core.models import (
    OrderCreate,
    OrderResponse,
    AgentState,
    OrchestratorInput,
    AgentTraceEntry,
)
from app.agents.graph import AgentGraph

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

    graph = AgentGraph(session)
    state = AgentState(
        order=OrchestratorInput(
            order_id=order_id,
            title=body.title,
            description=body.description,
            priority=body.priority,
        )
    )

    state = await graph.run(state)

    db_order.status = OrderStatus(state.status)
    db_order.cumulative_cost = state.cumulative_cost
    db_order.step_count = state.current_step
    if state.error:
        db_order.error_trace = {"error": state.error}

    for trace in state.traces:
        db_trace = AgentTraceDB(
            id=trace.id,
            order_id=order_id,
            agent_name=trace.agent_name,
            step_number=trace.step_number,
            input_summary=trace.input_summary,
            output_summary=trace.output_summary,
            output_json=trace.output_json,
            latency_ms=trace.latency_ms,
            cost_usd=trace.cost_usd,
            confidence=trace.confidence,
            status=trace.status,
            model_used=trace.model_used,
            cache_hit=trace.cache_hit,
        )
        session.add(db_trace)

    await session.commit()

    return _order_to_response(db_order, state)


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
    return _order_to_response(db_order)


def _order_to_response(db_order: OrderDB, state: AgentState | None = None) -> OrderResponse:
    traces = []
    if state and state.traces:
        traces = [t for t in state.traces]

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
