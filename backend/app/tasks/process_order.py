import uuid
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.db.session import async_session
from app.db.models import Order as OrderDB, AgentTrace as AgentTraceDB
from app.db.models import OrderStatus
from app.core.models import AgentState, OrchestratorInput, AgentTraceEntry
from app.agents.graph import AgentGraph
from app.core.model_router import ModelRouter
from app.cache.dlq import DeadLetterQueue
from app.cache.events import TracePublisher


@celery_app.task(bind=True, max_retries=2, default_retry_delay=5)
def process_order(self, order_id_str: str):
    import asyncio

    asyncio.run(_process_order(order_id_str, self))


async def _publish_trace(order_id_str: str, trace: AgentTraceEntry):
    publisher = TracePublisher()
    await publisher.publish(order_id_str, trace.model_dump())


async def _process_order(order_id_str: str, task):
    order_id = uuid.UUID(order_id_str)

    async with async_session() as session:
        result = await session.execute(select(OrderDB).where(OrderDB.id == order_id))
        db_order = result.scalar_one_or_none()
        if not db_order:
            return {"error": "Order not found"}

        db_order.status = OrderStatus.processing
        await session.commit()
        # A previous run may have left a done marker (failed → retry):
        # clear it so this run's stream cannot end on stale news.
        await TracePublisher().clear_done(order_id_str)

        try:
            graph = AgentGraph(
                session,
                on_trace=lambda t: _publish_trace(order_id_str, t),
            )
            state = AgentState(
                order=OrchestratorInput(
                    order_id=order_id,
                    title=db_order.title,
                    description=db_order.description,
                    priority=db_order.priority.value if hasattr(db_order.priority, "value") else db_order.priority,
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
            await TracePublisher().publish_done(order_id_str, state.status)
            return {"order_id": order_id_str, "status": state.status}

        except Exception as exc:
            db_order.status = OrderStatus.failed
            db_order.error_trace = {"error": str(exc)}
            await session.commit()
            if task.request.retries >= task.max_retries:
                # Retries exhausted: park the order on the dead-letter queue
                # for operator review instead of losing it silently.
                await DeadLetterQueue().push(
                    {
                        "order_id": order_id_str,
                        "title": db_order.title,
                        "error": str(exc),
                        "retries": task.request.retries,
                    }
                )
                await TracePublisher().publish_done(order_id_str, "failed")
            raise task.retry(exc=exc)
