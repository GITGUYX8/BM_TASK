from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4
from typing import Literal
from pydantic import BaseModel, Field


class OrchestratorInput(BaseModel):
    order_id: UUID
    title: str
    description: str
    priority: Literal["low", "medium", "high", "critical"]
    cumulative_cost: Decimal = Decimal("0.00")
    step_count: int = 0


class OrchestratorOutput(BaseModel):
    action: Literal["retrieve", "resolve", "verify", "complete", "escalate", "fail"]
    next_agent: str | None = None
    reason: str
    cumulative_cost: Decimal
    step_count: int


class RetrievedChunk(BaseModel):
    document_title: str
    chunk_text: str
    vector_score: float = 0.0
    keyword_score: float = 0.0
    fused_score: float = 0.0
    metadata: dict = Field(default_factory=dict)


class RetrieverQuery(BaseModel):
    order_id: UUID
    raw_query: str
    rewritten_query: str | None = None
    variants: list[str] = Field(default_factory=list)


class RetrieverResult(BaseModel):
    order_id: UUID
    chunks: list[RetrievedChunk] = Field(default_factory=list)
    retrieval_latency_ms: int = 0


class WorkerInput(BaseModel):
    order_id: UUID
    description: str
    retrieved_chunks: list[RetrievedChunk]
    model_tier: Literal["cheap", "capable"] = "capable"


class Resolution(BaseModel):
    order_id: UUID
    resolution_summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    actions_taken: list[str] = Field(default_factory=list)
    model_used: str = ""
    cost_usd: Decimal = Decimal("0.00")


class VerifierInput(BaseModel):
    order_id: UUID
    original_order: OrchestratorInput
    resolution: Resolution
    model_tier: Literal["cheap", "capable"] = "cheap"


class Verdict(BaseModel):
    order_id: UUID
    result: Literal["pass", "fail", "rework"]
    reason_code: str
    explanation: str
    confidence: float = Field(ge=0.0, le=1.0)
    model_used: str = ""
    cost_usd: Decimal = Decimal("0.00")


class AgentTraceEntry(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    agent_name: str
    step_number: int
    input_summary: str = ""
    output_summary: str = ""
    output_json: dict | None = None
    latency_ms: int = 0
    cost_usd: Decimal = Decimal("0.00")
    confidence: float | None = None
    status: Literal["ok", "retry", "failed", "escalated"] = "ok"
    model_used: str = ""
    cache_hit: bool = False


class AgentState(BaseModel):
    order: OrchestratorInput
    traces: list[AgentTraceEntry] = Field(default_factory=list)
    current_step: int = 0
    cumulative_cost: Decimal = Decimal("0.00")
    forced_cheap: bool = False
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)
    resolution: Resolution | None = None
    verdict: Verdict | None = None
    rework_count: int = 0
    status: Literal["processing", "completed", "failed", "escalated"] = "processing"
    error: str | None = None


class OrderCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    priority: Literal["low", "medium", "high", "critical"] = "medium"


class OrderResponse(BaseModel):
    order_id: UUID
    title: str
    description: str
    priority: str
    status: str
    cumulative_cost: Decimal = Decimal("0.00")
    step_count: int = 0
    traces: list[AgentTraceEntry] = Field(default_factory=list)
    error_trace: dict | None = None
    created_at: str = ""
    updated_at: str = ""


class DocumentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    metadata: dict = Field(default_factory=dict)


class DocumentResponse(BaseModel):
    document_id: UUID
    chunks_count: int
    status: str = "indexed"
