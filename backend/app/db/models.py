import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Column, String, Text, Integer, Float, Numeric, Enum, DateTime, ForeignKey, Boolean, JSON, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
import enum


class Base(DeclarativeBase):
    pass


class OrderPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class OrderStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"
    escalated = "escalated"


class TraceStatus(str, enum.Enum):
    ok = "ok"
    retry = "retry"
    failed = "failed"
    escalated = "escalated"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[OrderPriority] = mapped_column(Enum(OrderPriority), nullable=False, default=OrderPriority.medium)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), nullable=False, default=OrderStatus.queued)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    cumulative_cost: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0.00"))
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_trace: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    traces: Mapped[list["AgentTrace"]] = relationship("AgentTrace", back_populates="order", cascade="all, delete-orphan")


class AgentTrace(Base):
    __tablename__ = "agent_traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0.00"))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[TraceStatus] = mapped_column(Enum(TraceStatus), nullable=False, default=TraceStatus.ok)
    model_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    order: Mapped["Order"] = relationship("Order", back_populates="traces")

    __table_args__ = (
        Index("idx_agent_traces_order_id", "order_id"),
        Index("idx_agent_traces_order_step", "order_id", "step_number", unique=True),
    )


class DocumentChunk(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=True)
    doc_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("idx_documents_embedding", "embedding", postgresql_using="ivfflat", postgresql_with={"lists": 100}, postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("idx_documents_fts", "chunk_text", postgresql_using="gin", postgresql_ops={"chunk_text": "gin_trgm_ops"}),
    )
