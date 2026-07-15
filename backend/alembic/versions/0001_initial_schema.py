"""Initial schema: orders, agent_traces, documents tables

Revision ID: 0001
Revises:
Create Date: 2026-07-14
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import pgvector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("priority", sa.Enum("low", "medium", "high", "critical", name="orderpriority"), nullable=False, server_default="medium"),
        sa.Column("status", sa.Enum("queued", "processing", "completed", "failed", "escalated", name="orderstatus"), nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.String(64), nullable=True, unique=True),
        sa.Column("cumulative_cost", sa.Numeric(8, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("step_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error_trace", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "agent_traces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_name", sa.String(50), nullable=False),
        sa.Column("step_number", sa.Integer, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("input_summary", sa.Text, nullable=True),
        sa.Column("output_summary", sa.Text, nullable=True),
        sa.Column("output_json", postgresql.JSONB, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Numeric(8, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("status", sa.Enum("ok", "retry", "failed", "escalated", name="tracestatus"), nullable=False, server_default="ok"),
        sa.Column("model_used", sa.String(50), nullable=True),
        sa.Column("cache_hit", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_index("idx_agent_traces_order_id", "agent_traces", ["order_id"])
    op.create_index("idx_agent_traces_order_step", "agent_traces", ["order_id", "step_number"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(384), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.execute(
        "CREATE INDEX idx_documents_embedding ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX idx_documents_fts ON documents USING gin (to_tsvector('english', chunk_text))"
    )


def downgrade() -> None:
    op.drop_table("agent_traces")
    op.drop_table("documents")
    op.drop_table("orders")
    op.execute("DROP TYPE IF EXISTS orderpriority")
    op.execute("DROP TYPE IF EXISTS orderstatus")
    op.execute("DROP TYPE IF EXISTS tracestatus")
