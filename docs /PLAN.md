# Implementation Plan: AI Agent Pipeline — Work Order Processing System

> **Role:** Full-Stack AI Engineer  
> **Project:** Multi-Agent Work Order Processing System with RAG, Real-Time Streaming, and Observability  
> **Estimated Effort:** 23–29 hours  
> **Bootstrap:** `docker compose up`

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Tech Stack & Decisions](#2-tech-stack--decisions)
3. [Phase 1 — Foundation & Infrastructure](#3-phase-1--foundation--infrastructure)
4. [Phase 2 — RAG Pipeline](#4-phase-2--rag-pipeline)
5. [Phase 3 — Agent Pipeline (LangGraph)](#5-phase-3--agent-pipeline-langgraph)
6. [Phase 4 — FastAPI Backend & Celery](#6-phase-4--fastapi-backend--celery)
7. [Phase 5 — Next.js Frontend](#7-phase-5--nextjs-frontend)
8. [Phase 6 — Polish, Testing & Deliverables](#8-phase-6--polish-testing--deliverables)
9. [Bonus & Standout Features](#9-bonus--standout-features)
10. [Project Structure](#10-project-structure)

---

## 1. System Architecture Overview

The system processes work orders through a multi-agent AI pipeline. A user submits a work order via a Next.js frontend form, which POSTs to a FastAPI backend. The backend enqueues the order processing as a Celery task chain, where a LangGraph-based agent pipeline executes sequentially: an **Orchestrator** routes the order, a **RAG Retriever** fetches relevant context from a pgvector store, a **Worker** resolves the order using LLM + RAG context, and a **Verifier** validates the output against business rules. Every step is recorded as an agent trace, streamed to the frontend via Server-Sent Events (SSE), and persisted in PostgreSQL. Cost is tracked per order ($0.05 ceiling), LLM responses are cached in Redis, and the model router switches between cheap and capable model tiers based on task complexity.

### Data Flow

```
User → [Next.js Form] → POST /orders → FastAPI → Celery Chain
                                                      │
                          ┌───────────────────────────┘
                          ▼
                    [Orchestrator Agent]
                          │
                    Enforce step/cost budget
                          │
                          ▼
                    [RAG Retriever Agent]
                          │
                    Query rewriting → Multi-query → Hybrid search (pgvector <=> + tsvector)
                    → Reranking → top-3 chunks
                          │
                          ▼
                    [Worker Agent]
                          │
                    LLM (capable model) + RAG context → Structured Resolution
                          │
                          ▼
                    [Verifier Agent]
                          │
                    LLM (cheap model) → pass/fail/rework
                          │
                    ┌─────┴─────┐
                    ▼           ▼
              completed      rework (loop back to Worker, max 2x)
                                          │
                                    fail → human-in-the-loop flag

Every step → Agent Trace → PostgreSQL → SSE stream → Next.js UI
```

---

## 2. Tech Stack & Decisions

| Layer | Technology | Version / Detail | Rationale |
|---|---|---|---|
| **Frontend** | TypeScript, React, Next.js | App Router (>=14) | JD explicit requirement |
| **State** | Zustand | Latest | User choice — lightweight, SSE-friendly |
| **Streaming** | Server-Sent Events | Native `EventSource` | JD requirement, simpler than WebSockets for one-way |
| **Backend** | Python FastAPI | >=0.110 | JD: "undisputed king" |
| **Agent Framework** | LangGraph | Latest | User choice — graph-based state management |
| **Async Queue** | Celery | >=5.4 with Redis broker | JD explicit requirement |
| **Database** | PostgreSQL 16 + pgvector | 0.7+ | JD explicit requirement — hybrid search |
| **Cache** | Redis 7 | Stack | JD requirement — LLM cache, rate limiter, Celery backend |
| **LLM** | Gemini API + Groq (flexible abstraction) | Free-tier | Start free, swap to paid (OpenAI/Anthropic) later |
| **Embeddings** | SentenceTransformers | `all-MiniLM-L6-v2` | Fully free, local, no API key |
| **Structured Output** | Instructor (Python) + Pydantic | Instructor>=1.0 | JD requirement — type-safe LLM outputs |
| **Containerization** | Docker Compose | V2 | Single-command bootstrap |

### LLM Abstraction Strategy

Build a `LLMClient` abstract base class with implementations:

- `GroqClient` — free Llama 3 8B (cheap) / Llama 3 70B (capable), 30 req/min
- `GeminiClient` — free Gemini 1.5 Flash (cheap) / Gemini 1.5 Pro (capable), 60 req/min
- `OpenAIClient` — paid fallback, GPT-4o-mini (cheap) / GPT-4o (capable)
- `AnthropicClient` — paid fallback, Claude Haiku (cheap) / Claude Sonnet (capable)

Selection via environment variable `LLM_PROVIDER`. All return structured Pydantic outputs via Instructor.

---

## 3. Phase 1 — Foundation & Infrastructure

**Time:** ~3-4 hours  
**Goal:** Working Docker Compose environment with all services, database schema, Pydantic contracts, and project scaffolding.

### 3.1 Docker Compose (`docker-compose.yml`)

```yaml
Services:
  - postgres:16-pgvector
      port 5432, volume for persistence, healthcheck
  - redis:7-alpine
      port 6379
  - backend:
      build: ./backend
      ports 8000, depends on postgres+redis, env vars
  - frontend:
      build: ./frontend
      ports 3000, depends on backend
  - celery-worker:
      build: ./backend
      command: celery -A app.celery_app worker
      depends on backend+redis
```

### 3.2 PostgreSQL Schema (via SQLAlchemy + Alembic)

**`orders` table:**
| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK, generated on submit |
| `title` | VARCHAR(255) | From work order form |
| `description` | TEXT | Raw work order text |
| `priority` | ENUM('low','medium','high','critical') | |
| `status` | ENUM('queued','processing','completed','failed','escalated') | State machine |
| `idempotency_key` | VARCHAR(64) | Unique, nullable |
| `cumulative_cost` | NUMERIC(6,5) | Tracks $ spent on LLM calls |
| `step_count` | INTEGER | Current agent turn count |
| `error_trace` | JSONB | Structured error if failed |
| `created_at` | TIMESTAMPTZ | |
| `updated_at` | TIMESTAMPTZ | |

**`agent_traces` table:**
| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `order_id` | UUID | FK → orders |
| `agent_name` | VARCHAR(50) | orchestrator/retriever/worker/verifier |
| `step_number` | INTEGER | Monotonic per order |
| `input_hash` | VARCHAR(64) | SHA-256 of serialized input |
| `input_summary` | TEXT | Truncated input for UI |
| `output_summary` | TEXT | Truncated output for UI |
| `output_json` | JSONB | Full structured output |
| `latency_ms` | INTEGER | Wall-clock time |
| `cost_usd` | NUMERIC(6,5) | Cost of this LLM call |
| `confidence` | FLOAT | 0.0–1.0 (from worker) |
| `status` | ENUM('ok','retry','failed','escalated') | |
| `model_used` | VARCHAR(50) | Which model tier handled it |
| `cache_hit` | BOOLEAN | Whether response came from Redis |
| `created_at` | TIMESTAMPTZ | |

**`documents` table (embeddings):**
| Column | Type | Notes |
|---|---|---|
| `id` | UUID | PK |
| `title` | VARCHAR(255) | Document title |
| `content` | TEXT | Original content |
| `chunk_index` | INTEGER | Position in document |
| `chunk_text` | TEXT | The chunk text |
| `embedding` | vector(384) | From `all-MiniLM-L6-v2` |
| `metadata` | JSONB | Arbitrary metadata |
| `created_at` | TIMESTAMPTZ | |

pgvector index: `CREATE INDEX ON documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);`

Full-text search: `GIN INDEX ON documents USING gin(to_tsvector('english', chunk_text));`

### 3.3 Pydantic Agent Contracts

Every agent declares its input/output schemas as Pydantic models. These serve as the **typed contracts** between agents.

```python
# Orchestrator
class OrchestratorInput(BaseModel):
    order_id: UUID
    title: str
    description: str
    priority: Literal["low", "medium", "high", "critical"]
    cumulative_cost: Decimal  # current running cost
    step_count: int           # current step number

class OrchestratorOutput(BaseModel):
    action: Literal["retrieve", "resolve", "verify", "complete", "escalate", "fail"]
    next_agent: str | None
    reason: str
    cumulative_cost: Decimal
    step_count: int

# RAG Retriever
class RetrieverQuery(BaseModel):
    order_id: UUID
    raw_query: str
    rewritten_query: str | None = None
    variants: list[str] = []

class RetrieverResult(BaseModel):
    order_id: UUID
    chunks: list[RetrievedChunk]
    retrieval_latency_ms: int

class RetrievedChunk(BaseModel):
    document_title: str
    chunk_text: str
    vector_score: float
    keyword_score: float
    fused_score: float
    metadata: dict

# Worker
class WorkerInput(BaseModel):
    order_id: UUID
    description: str
    retrieved_chunks: list[RetrievedChunk]
    model_tier: Literal["cheap", "capable"]

class Resolution(BaseModel):
    order_id: UUID
    resolution_summary: str
    confidence: float  # 0.0–1.0
    actions_taken: list[str]
    model_used: str
    cost_usd: Decimal

# Verifier
class VerifierInput(BaseModel):
    order_id: UUID
    original_order: OrchestratorInput
    resolution: Resolution
    model_tier: Literal["cheap", "capable"]

class Verdict(BaseModel):
    order_id: UUID
    result: Literal["pass", "fail", "rework"]
    reason_code: str      # e.g., "INSUFFICIENT_EVIDENCE", "BUSINESS_RULE_VIOLATION"
    explanation: str
    confidence: float
    model_used: str
    cost_usd: Decimal
```

### 3.4 Backend Scaffolding

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app factory
│   ├── celery_app.py            # Celery instance + task definitions
│   ├── config.py                # Pydantic Settings (env vars)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── orders.py            # POST/GET /orders, GET /orders/:id/stream
│   │   ├── documents.py         # POST /documents
│   │   └── errors.py            # Structured error handlers
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract base agent
│   │   ├── orchestrator.py
│   │   ├── retriever.py
│   │   ├── worker.py
│   │   └── verifier.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py            # All Pydantic models
│   │   ├── model_router.py      # Cheap/capable model selection
│   │   └── cost_tracker.py      # Cost ceiling enforcement
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── chunker.py
│   │   ├── embedding.py
│   │   ├── retriever.py         # Hybrid search logic
│   │   ├── rewriter.py
│   │   ├── multi_query.py
│   │   └── reranker.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py           # Async SQLAlchemy session
│   │   ├── models.py            # ORM models
│   │   └── migrations/          # Alembic
│   └── cache/
│       ├── __init__.py
│       └── redis.py             # LLM cache + rate limiter
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_agents.py
│   ├── test_rag.py
│   └── test_integration.py
├── scripts/
│   └── seed_documents.py        # Ingest 10+ demo docs
├── requirements.txt
└── Dockerfile
```

---

## 4. Phase 2 — RAG Pipeline

**Time:** ~4-5 hours  
**Goal:** A production-grade RAG pipeline: ingest documents → chunk → embed → hybrid search → query rewrite → multi-query → rerank.

### 4.1 Document Chunking (`chunker.py`)

**Strategy:** Recursive Character Text Splitter (LangChain's `RecursiveCharacterTextSplitter`)

| Parameter | Value | Rationale |
|---|---|---|
| Chunk size | 1000 tokens | Within 500–1500 range per JD |
| Overlap | 200 tokens | Maintains context across boundaries |
| Separators | `["\n\n", "\n", ".", " ", ""]` | Respect semantic boundaries |

```python
def chunk_document(title: str, content: str, metadata: dict) -> list[DocumentChunk]:
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""]
    )
    texts = splitter.split_text(content)
    return [DocumentChunk(title=title, chunk_text=t, chunk_index=i, metadata=metadata)
            for i, t in enumerate(texts)]
```

### 4.2 Embedding (`embedding.py`)

**Model:** `sentence-transformers/all-MiniLM-L6-v2`  
**Dimension:** 384  
**Distance:** Cosine (pgvector `<=>` operator)

```python
class EmbeddingService:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts).tolist()
```

### 4.3 Hybrid Search (`retriever.py`)

Combines vector similarity with keyword full-text search via weighted fusion.

**Vector search:** pgvector `<=>` cosine distance  
**Keyword search:** PostgreSQL `to_tsvector('english', chunk_text) @@ to_tsquery('english', query)`  

**Fusion formula:**
```
fused_score = (1 - vector_distance) * 0.7 + keyword_rank * 0.3
```

Where `keyword_rank` is normalized BM25-like relevance from `ts_rank(to_tsvector, query)`.

```sql
SELECT d.id, d.chunk_text, d.title, d.metadata,
       1 - (d.embedding <=> :query_embedding) AS vector_score,
       ts_rank(to_tsvector('english', d.chunk_text), to_tsquery('english', :keyword_query)) AS keyword_score
FROM documents d
WHERE d.embedding <=> :query_embedding < :threshold  -- 0.8 for cosine
   OR to_tsvector('english', d.chunk_text) @@ to_tsquery('english', :keyword_query)
ORDER BY (1 - (d.embedding <=> :query_embedding)) * 0.7 + 
         ts_rank(to_tsvector('english', d.chunk_text), to_tsquery('english', :keyword_query)) * 0.3 DESC
LIMIT 10;
```

### 4.4 Query Rewriting (`rewriter.py`)

Before retrieval, the raw work order is rewritten into a search-optimized query.

**Technique:** LLM call (cheap model) with a few-shot prompt.

```
System: You are a query rewriting assistant. Given a work order description,
rewrite it into a concise search query optimized for a knowledge base retrieval system.
Expand abbreviations, extract key entities, and remove filler words.

Few-shot examples:
  "my laptop won't boot after latest update, got error code 0x800F0922"
  → "Windows update error 0x800F0922 boot failure resolve"

  "need to reset MFA for user jdoe@acme.com, lost phone"
  → "MFA reset lost phone user jdoe@acme.com Okta"

Input: {work_order_description}
Output: (single line query)
```

### 4.5 Multi-Query Expansion (`multi_query.py`)

Generate 2–3 query variants to improve recall, then deduplicate results.

**Technique:** Another cheap LLM call generating alternative phrasings.

```
Generate 2 alternative search queries for:
"{rewritten_query}"

Return as a JSON array of strings.
```

Retrieve for each variant, then deduplicate by `chunk_text` (exact match) keeping the highest score.

### 4.6 Reranking (`reranker.py`)

Rerank the deduplicated chunks by relevance to the _original_ work order.

**Technique:** Cross-encoder reranking via `cross-encoder/ms-marco-MiniLM-L-6-v2` (lightweight, local).

```python
def rerank(query: str, chunks: list[RetrievedChunk], top_k: int = 3) -> list[RetrievedChunk]:
    pairs = [[query, c.chunk_text] for c in chunks]
    scores = cross_encoder.predict(pairs)
    scored = list(zip(chunks, scores))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [c for c, s in scored[:top_k]]
```

### 4.7 Demo Document Seed Set

Ingest at least 10 documents covering diverse IT support scenarios:

| # | Title | Topic |
|---|---|---|
| 1 | VPN Connection Troubleshooting Guide | Network |
| 2 | Password Reset Procedure | IAM |
| 3 | Software Installation Policy | Compliance |
| 4 | Hardware Replacement Workflow | Procurement |
| 5 | Data Breach Incident Response Plan | Security |
| 6 | Email Migration to Office 365 | Migration |
| 7 | Server Patching Schedule | Maintenance |
| 8 | Employee Offboarding Checklist | HR/IT |
| 9 | API Rate Limiting Best Practices | Development |
| 10 | Database Backup and Recovery SOP | Operations |
| 11 | Work Order Escalation Matrix | Process |
| 12 | LLM Output Validation Rules | AI Governance |

---

## 5. Phase 3 — Agent Pipeline (LangGraph)

**Time:** ~5-6 hours  
**Goal:** 4 LangGraph agents with typed contracts, model router, cost tracking, Redis cache.

### 5.1 Agent Base Class (`base.py`)

```python
class AgentNode:
    name: str
    model_tier: Literal["cheap", "capable"]

    async def run(self, state: AgentState) -> AgentState:
        """Pure function: takes state, returns new state."""
        raise NotImplementedError
```

### 5.2 LangGraph State Definition

```python
class AgentState(TypedDict):
    order: OrchestratorInput
    traces: list[AgentTraceEntry]
    current_step: int
    cumulative_cost: Decimal
    retrieved_chunks: list[RetrievedChunk]
    resolution: Resolution | None
    verdict: Verdict | None
    rework_count: int
    status: Literal["processing", "completed", "failed", "escalated"]
    error: str | None
```

### 5.3 Graph Topology

```python
from langgraph.graph import StateGraph, END

workflow = StateGraph(AgentState)

workflow.add_node("orchestrator", OrchestratorNode().run)
workflow.add_node("retriever", RetrieverNode().run)
workflow.add_node("worker", WorkerNode().run)
workflow.add_node("verifier", VerifierNode().run)

workflow.set_entry_point("orchestrator")

workflow.add_conditional_edges(
    "orchestrator",
    lambda state: state["next_action"],
    {
        "retrieve": "retriever",
        "resolve": "worker",
        "verify": "verifier",
        "complete": END,
        "escalate": END,
        "fail": END,
    }
)

workflow.add_edge("retriever", "orchestrator")  # back to orchestrator
workflow.add_conditional_edges(
    "verifier",
    lambda state: "rework" if state["verdict"].result == "rework" and state["rework_count"] < 2 else "complete" if state["verdict"].result == "pass" else "fail",
    {
        "rework": "worker",      # loop to worker with improved context
        "complete": END,
        "fail": END,
    }
)
```

### 5.4 Agent Implementations

#### Orchestrator Node

**Logic:**
1. Accept `Order`, check step budget (max 8 turns)
2. Check cumulative cost against ceiling ($0.05)
3. Route to next agent based on state:
   - Step 1 → `retrieve`
   - After retriever → `resolve`
   - After worker → `verify`
   - After verifier (pass) → `complete`
   - After verifier (rework, <2 attempts) → `resolve`
   - After verifier (rework, >=2 attempts) → `escalate`
   - After verifier (fail) → `fail`
4. Enforce: if cumulative_cost > $0.05 → switch all remaining steps to cheap model
5. If step_count >= 8 → force `complete` with error flag

#### RAG Retriever Node

**Logic:**
1. Call `rewriter.rewrite(order.description)`
2. Call `multi_query.expand(rewritten_query)` → 2-3 variants
3. For each variant, call `hybrid_search(query, top_k=10)`
4. Deduplicate by chunk_text
5. Call `reranker.rerank(original_query, deduplicated, top_k=3)`
6. Log: retrieval_latency_ms, scores per chunk
7. Return top-3 chunks + latency

#### Worker Node

**Logic:**
1. Model selection: if step 1 (initial resolve) → capable model; if rework → cheap model
2. Build prompt: system prompt + RAG chunks + work order
3. Call LLM with Instructor to get structured `Resolution`
4. If LLM fails → retry with cheap model as fallback
5. Calculate cost (token count × model rate)
6. Log trace entry
7. Return resolution

**Worker Prompt Design:**
```
You are a work order resolution specialist. Given the work order description
and relevant knowledge base documents, produce a structured resolution.

Work Order: {description}
Priority: {priority}

Relevant KB Documents:
{chunks}

Rules:
- Base your resolution on the provided documents
- If documents don't cover the issue, state that clearly
- Assign a confidence score based on how well the evidence supports your answer
- List specific actions taken

Output format: Resolution(resolution_summary, confidence, actions_taken)
```

#### Verifier Node

**Logic:**
1. Model selection: always cheap model (verification is simpler)
2. Build prompt: original order + worker's resolution + business rules
3. Call LLM with Instructor to get structured `Verdict`
4. If `fail` or `rework`, the verifier overrules the worker (the verdict replaces the resolution)
5. On `rework` with count >= 2 → set flag for human review

**Verifier Prompt Design:**
```
You are a quality assurance verifier. Given the original work order and the
proposed resolution, determine if the resolution is correct.

Original Work Order: {description}
Priority: {priority}
Resolution: {resolution_summary} (confidence: {confidence})
Actions Taken: {actions_taken}

Business Rules:
1. Critical priority orders must have at least 2 actions listed
2. High-priority orders must be resolved within 3 steps
3. All resolutions must reference at least one KB document
4. Confidence must not exceed actual evidence quality
5. Resolution must directly address the described issue

Output format: Verdict(result, reason_code, explanation, confidence)
```

### 5.5 Model Router (`model_router.py`)

```python
MODEL_TIERS = {
    "cheap": {
        "groq": "llama3-8b-8192",       # $0.00 (free tier)
        "gemini": "gemini-1.5-flash",    # $0.00 (free tier)
        "openai": "gpt-4o-mini",         # $0.15/1M input
        "anthropic": "claude-3-haiku",   # $0.25/1M input
    },
    "capable": {
        "groq": "llama3-70b-8192",      # $0.00 (free tier)
        "gemini": "gemini-1.5-pro",      # $0.00 (free tier)
        "openai": "gpt-4o",              # $2.50/1M input
        "anthropic": "claude-3-sonnet",  # $3.00/1M input
    }
}

class ModelRouter:
    def select(self, tier: str, provider: str) -> str:
        return MODEL_TIERS[tier][provider]

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> Decimal:
        # Calculate based on model pricing
        ...
```

### 5.6 Cost Tracker (`cost_tracker.py`)

```python
COST_CEILING = Decimal("0.05")  # $0.05 per work order

class CostTracker:
    def __init__(self):
        self.cumulative_cost = Decimal("0.00")
        self.forced_cheap = False

    def add_cost(self, cost: Decimal):
        self.cumulative_cost += cost
        if self.cumulative_cost > COST_CEILING:
            self.forced_cheap = True  # All subsequent calls use cheap model

    def within_budget(self) -> bool:
        return self.cumulative_cost <= COST_CEILING
```

### 5.7 Redis LLM Cache (`cache/redis.py`)

**Cache key:** `llm:{model}:{sha256(prompt)}:{temperature}`  
**TTL:** 3600 seconds (1 hour)  
**Value:** Serialized LLM response JSON

```python
class LLMCache:
    async def get(self, model: str, prompt: str, temperature: float) -> dict | None:
        key = self._make_key(model, prompt, temperature)
        data = await self.redis.get(key)
        if data:
            await self.redis.incr(f"stats:cache_hits")
            return json.loads(data)
        await self.redis.incr(f"stats:cache_misses")
        return None

    async def set(self, model: str, prompt: str, temperature: float, response: dict):
        key = self._make_key(model, prompt, temperature)
        await self.redis.setex(key, 3600, json.dumps(response))
```

---

## 6. Phase 4 — FastAPI Backend & Celery

**Time:** ~4-5 hours  
**Goal:** All API endpoints working with Celery task chain, SSE streaming, idempotency, structured errors.

### 6.1 API Endpoints

#### `POST /orders`

**Request:**
```json
{
  "title": "Laptop won't boot",
  "description": "Dell XPS 15, error 0x800F0922 after Windows update",
  "priority": "high"
}
```

**Headers:** `Idempotency-Key: <uuid>` (optional)

**Response (202 Accepted):**
```json
{
  "order_id": "uuid",
  "status": "queued",
  "created_at": "2026-07-14T12:00:00Z"
}
```

**Logic:**
1. Check idempotency key (if provided) → return existing order if found
2. Create order in DB (status = `queued`)
3. Enqueue Celery chain: `process_order.delay(order_id)`
4. Return 202 with order_id

#### `GET /orders/:id`

**Response (200):**
```json
{
  "order_id": "uuid",
  "title": "...",
  "description": "...",
  "priority": "high",
  "status": "completed",
  "cumulative_cost": 0.0032,
  "step_count": 4,
  "traces": [
    {
      "agent_name": "orchestrator",
      "step_number": 1,
      "input_summary": "...",
      "output_summary": "Route to retriever",
      "latency_ms": 45,
      "cost_usd": 0.0001,
      "confidence": null,
      "status": "ok",
      "model_used": "gemini-1.5-flash",
      "cache_hit": false
    },
    {
      "agent_name": "retriever",
      "step_number": 2,
      "input_summary": "...",
      "output_summary": "3 chunks retrieved",
      "latency_ms": 230,
      "cost_usd": 0.0,
      "confidence": null,
      "status": "ok",
      "model_used": "N/A",
      "cache_hit": false,
      "retrieved_chunks": [
        {"document_title": "...", "score": 0.92, "snippet": "..."}
      ]
    }
    // ... more steps
  ],
  "error_trace": null,
  "created_at": "...",
  "updated_at": "..."
}
```

#### `GET /orders/:id/stream` (SSE)

**Protocol:** Server-Sent Events

```
event: step
data: {"order_id":"...","agent_name":"worker","step_number":3,"status":"processing","output_summary":"..."}

event: step
data: {"order_id":"...","agent_name":"verifier","step_number":4,"status":"completed","output_summary":"passed"}

event: complete
data: {"order_id":"...","status":"completed","cumulative_cost":0.0032}

event: error
data: {"order_id":"...","status":"failed","error":"Budget exceeded"}
```

**Implementation:** Use Redis Pub/Sub. Each Celery task publishes its step result to a channel `order:{order_id}:events`. The SSE endpoint subscribes to that channel.

```python
@router.get("/orders/{order_id}/stream")
async def stream_order(order_id: UUID):
    async def event_generator():
        pubsub = redis.pubsub()
        await pubsub.subscribe(f"order:{order_id}:events")
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield f"event: step\ndata: {message['data']}\n\n"
                data = json.loads(message["data"])
                if data["status"] in ("completed", "failed", "escalated"):
                    break
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

#### `POST /documents`

**Request:**
```json
{
  "title": "VPN Troubleshooting Guide",
  "content": "Full document content...",
  "metadata": {"category": "network", "author": "IT"}
}
```

**Response (201):**
```json
{
  "document_id": "uuid",
  "chunks_count": 12,
  "status": "indexed"
}
```

**Logic:**
1. Chunk document
2. Embed each chunk
3. Bulk insert into `documents` table
4. Return document_id + chunk count

#### `GET /docs`

FastAPI auto-generated OpenAPI docs at `/docs`.

### 6.2 Structured Error Handling

All errors return:

```json
{
  "error": {
    "code": "ORDER_NOT_FOUND",
    "message": "Order with ID xyz not found",
    "details": {"order_id": "xyz"}
  }
}
```

Common error codes:
| Code | HTTP Status | When |
|---|---|---|
| `ORDER_NOT_FOUND` | 404 | Invalid order ID |
| `ORDER_PROCESSING` | 409 | Conflict on retry while processing |
| `VALIDATION_ERROR` | 422 | Invalid input |
| `IDEMPOTENCY_MISMATCH` | 409 | Different body with same idempotency key |
| `LLM_API_ERROR` | 502 | LLM provider returned error |
| `BUDGET_EXCEEDED` | 402 | Cost ceiling hit |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Unexpected error |

### 6.3 Celery Task Chain

```python
from celery import chain

@app.post("/orders")
async def create_order(order: OrderCreate, idempotency_key: str = Header(None)):
    # ... create order in DB ...
    chain(
        orchestrate_step.s(order_id),
        retrieve_step.s(),
        worker_step.s(),
        verify_step.s(),
    ).apply_async()
    return {"order_id": order_id, "status": "queued"}
```

Each task:
1. Receives the agent state JSON
2. Executes the agent node
3. Publishes step result to Redis Pub/Sub channel
4. Saves trace entry to DB
5. Returns updated state for next task

**Retry policy:** Each task has `max_retries=2, default_retry_delay=5`.

```python
@celery.task(bind=True, max_retries=2, default_retry_delay=5)
def worker_step(self, state: dict):
    try:
        node = WorkerNode()
        new_state = node.run(state)
        publish_step_event(new_state)
        save_trace(new_state)
        return new_state
    except Exception as exc:
        self.retry(exc=exc)
```

---

## 7. Phase 5 — Next.js Frontend

**Time:** ~4-5 hours  
**Goal:** Full-featured dashboard: submit order, list orders, real-time SSE trace with expandable timeline.

### 7.1 Pages

#### `/` — Home (Order Submission Form)

```
┌─────────────────────────────────────┐
│  Submit Work Order                   │
│                                     │
│  Title:    [____________________]   │
│  Priority: [low|medium|high|crit] ▼ │
│  Description:                       │
│  [                                ] │
│  [                                ] │
│                                     │
│  [Submit Order]                     │
│                                     │
│  ─── Recent Orders ───              │
│  • Laptop won't boot    ┌──────┐   │
│    high | Jul 14 12:00  │✓ done│   │
│  • Reset MFA for jdoe   └──────┘   │
│    medium | Jul 14 11:45 │→ proc│   │
│  • New server request   └──────┘   │
│    low | Jul 14 11:30   │● queud│   │
│  ─────────────────────  └──────┘   │
└─────────────────────────────────────┘
```

#### `/orders/[id]` — Order Detail + Agent Trace

```
┌─────────────────────────────────────┐
│  Order: Laptop won't boot       ◄ Back
│  Priority: High | Status: ● Processing
│  Cost: $0.0032 / $0.05 ceiling
│  Steps: 3 / 8
│                                     │
│  ─── Agent Trace ───               │
│                                     │
│  [1] Orchestrator ── 45ms ─ $0.0001│
│  │   Input: Work order received     │
│  │   Output: Route to retriever     │
│  ├──────────────────────────────────┤
│  [2] RAG Retriever ─ 230ms ─ $0    │
│  │   Input: "Windows update error"  │
│  │   Output: 3 chunks found         │
│  │   ┌─── Retrieved Chunks ───┐     │
│  │   │ • VPN Guide          0.92│   │
│  │   │ • Patch Schedule     0.87│   │
│  │   │ • Error Codes DB     0.81│   │
│  │   └────────────────────────┘     │
│  ├──────────────────────────────────┤
│  ⏳ [3] Worker ─ in progress...     │
│                                     │
│  (auto-scrolls as events arrive)    │
└─────────────────────────────────────┘
```

### 7.2 Zustand Store (`store/orders.ts`)

```typescript
interface OrderStore {
  orders: Record<string, Order>;
  currentOrderId: string | null;

  // Actions
  submitOrder: (data: OrderInput) => Promise<string>;
  fetchOrder: (id: string) => Promise<void>;
  fetchOrders: () => Promise<void>;

  // SSE
  connectStream: (orderId: string) => void;
  disconnectStream: () => void;

  // Real-time updates from SSE
  appendTraceStep: (orderId: string, step: TraceStep) => void;
  updateOrderStatus: (orderId: string, status: OrderStatus) => void;

  // UI
  expandedSteps: Set<number>;
  toggleStep: (stepNumber: number) => void;
}
```

### 7.3 SSE Client Hook (`lib/sse.ts`)

```typescript
function useOrderStream(orderId: string | null) {
  const appendTraceStep = useOrderStore(s => s.appendTraceStep);
  const updateOrderStatus = useOrderStore(s => s.updateOrderStatus);

  useEffect(() => {
    if (!orderId) return;

    const eventSource = new EventSource(`/api/orders/${orderId}/stream`);

    eventSource.addEventListener('step', (e) => {
      const step = JSON.parse(e.data);
      appendTraceStep(orderId, step);
    });

    eventSource.addEventListener('complete', (e) => {
      const result = JSON.parse(e.data);
      updateOrderStatus(orderId, result.status);
      eventSource.close();
    });

    eventSource.addEventListener('error', (e) => {
      const error = JSON.parse(e.data);
      updateOrderStatus(orderId, 'failed');
      // Show inline error
      eventSource.close();
    });

    return () => eventSource.close();
  }, [orderId]);
}
```

### 7.4 Key Components

| Component | File | Responsibility |
|---|---|---|
| `OrderForm` | `components/OrderForm.tsx` | Form with validation, submit via fetch |
| `OrderList` | `components/OrderList.tsx` | Table/cards of orders with live status |
| `StatusBadge` | `components/StatusBadge.tsx` | Color-coded status pill |
| `AgentTrace` | `components/AgentTrace.tsx` | Timeline container |
| `TraceStep` | `components/TraceStep.tsx` | Expandable step card |
| `RetrievedChunks` | `components/RetrievedChunks.tsx` | Expandable chunk list with scores |
| `CostBar` | `components/CostBar.tsx` | Visual cost vs ceiling progress |
| `ErrorAlert` | `components/ErrorAlert.tsx` | Inline error state display |

### 7.5 Error Handling States

The frontend must handle these inline errors:

| Error | Visual | Recovery |
|---|---|---|
| Agent failure | Red alert with error code + message | "Retry" button → POST /orders/:id/retry |
| Budget exceeded | Yellow warning, cost bar at 100% | Shows which steps used cheap model |
| API down | Toast notification, retry button | Exponential backoff reconnect |
| Timeout | Orange alert on step card | Shows partial trace up to timeout |
| Validation error | Inline field errors on form | Fix and resubmit |

---

## 8. Phase 6 — Polish, Testing & Deliverables

**Time:** ~3-4 hours  
**Goal:** Integration test, unit tests, README, ARCHITECTURE.md, DECISIONS.md, seed script.

### 8.1 Testing

#### Integration Test (`tests/test_integration.py`)

```python
@pytest.mark.asyncio
async def test_full_pipeline():
    """Submit a work order → pipeline processes → verify trace exists."""
    # 1. Submit order via POST /orders
    # 2. Wait for Celery chain to complete (poll GET /orders/:id)
    # 3. Assert status == "completed"
    # 4. Assert trace has entries for all 4 agents
    # 5. Assert cumulative_cost > 0
    # 6. Assert trace entries have latency, model_used, cache_hit
    # 7. Assert worker output has confidence and resolution_summary
    # 8. Assert verifier output has result, reason_code, explanation
```

#### Unit Tests (`tests/test_agents.py`)

```python
@pytest.mark.asyncio
async def test_orchestrator_routes_to_retriever():
    state = AgentState(order=Order(...), current_step=1)
    result = await OrchestratorNode().run(state)
    assert result["next_action"] == "retrieve"

@pytest.mark.asyncio
async def test_verifier_rejects_low_confidence():
    resolution = Resolution(confidence=0.3, ...)
    result = await VerifierNode().run(VerifierInput(resolution=resolution, ...))
    assert result.result == "fail"

@pytest.mark.asyncio
async def test_cost_ceiling_enforces_cheap_model():
    state = AgentState(cumulative_cost=Decimal("0.05"), ...)
    result = await OrchestratorNode().run(state)
    assert result["forced_cheap"] == True
```

#### RAG Tests (`tests/test_rag.py`)

```python
def test_chunking_respects_size():
    chunks = chunk_document("Test", "A" * 5000, {})
    assert all(len(c.chunk_text.split()) <= 1000 for c in chunks)

def test_hybrid_search_returns_results():
    chunks = hybrid_search("error 0x800F0922", top_k=3)
    assert len(chunks) <= 3
    assert all(c.fused_score > 0 for c in chunks)
```

### 8.2 Seed Script (`scripts/seed_documents.py`)

```bash
python scripts/seed_documents.py --count 12
```

Ingests 12 pre-written IT support documents into the RAG store. Each document:
- 1–5 pages of realistic content
- Structured metadata (category, author, version)
- Chunked, embedded, stored in pgvector

### 8.3 Deliverable Documents

#### `README.md`

Sections:
- **Architecture Overview** (1-paragraph summary)
- **Setup Instructions**: Prerequisites (Docker, git), env vars (LLM API keys, DB creds)
- **Quick Start**: `docker compose up` — single command
- **Environment Variables Table**:
  | Variable | Default | Description |
  |---|---|---|
  | `LLM_PROVIDER` | `gemini` | Provider: gemini, groq, openai, anthropic |
  | `LLM_API_KEY` | — | API key for selected provider |
  | `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
  | `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |
  | `COST_CEILING` | `0.05` | Max $ per work order |
  | `MAX_STEPS` | `8` | Max agent turns per order |
- **Run Contract**: Exactly `docker compose up` and how to verify it's running
- **How to Trigger a Demo**: curl commands + UI walkthrough

#### `ARCHITECTURE.md`

- ASCII component diagram (same as Section 1 of this document)
- Data flow diagram (submit → enqueue → agent chain → RAG → stream → display)
- Agent contract schemas (the Pydantic models)
- Technology choices per component with rationale table
- Database schema diagram (ASCII or description)
- SSE event protocol specification

#### `DECISIONS.md`

Document key trade-offs:

| Decision | Options Considered | Chosen | Rationale |
|---|---|---|---|
| Agent framework | LangGraph, CrewAI, AutoGen, raw | LangGraph | Graph-based state management, built-in conditional edges, typed state |
| Chunk strategy | Recursive character, semantic, token-aware | Recursive character | Best balance of simplicity and quality; semantic chunking adds complexity without proportional gain for IT docs |
| Model routing | Single model, 2 tiers, 3+ tiers | 2 tiers (cheap/capable) | Matches JD requirement; 3+ tiers overcomplicates for this scale |
| Cache invalidation | TTL-only, LRU, write-through | TTL-only (1 hour) | Simple, predictable; LLM responses are idempotent for same inputs |
| Query rewriting | LLM-based, rule-based, hybrid | LLM-based (few-shot) | More robust for diverse work order descriptions |
| Why verifier overrules worker | Worker has final say vs verifier overrules | Verifier overrules | Worker may hallucinate; verifier is the quality gate; matches production patterns |
| Embedding model | OpenAI ada-002, Cohere, SentenceTransformers | SentenceTransformers `all-MiniLM-L6-v2` | Free, local, no API key needed, 384-dim is sufficient for this domain |
| SSE vs WebSockets | SSE, WebSockets, polling | SSE | Simpler (native EventSource), one-directional (server→client), auto-reconnect |
| State management | Zustand, Redux, Context API | Zustand | Lightweight, minimal boilerplate, SSE-friendly updates |

---

## 9. Bonus & Standout Features

These are explicitly called out in the task tips as differentiators:

### 9.1 Cost-Per-Order Tracking in Frontend

A visual bar showing `$0.0032 / $0.05` with a color gradient (green → yellow → red), updated live as each step's cost arrives via SSE.

### 9.2 Human-in-the-Loop

When the verifier rejects output twice (2 rework attempts), the order status is set to `escalated` and flagged for manual review. A separate `GET /orders?status=escalated` endpoint lists orders needing human attention.

### 9.3 Retry Failed Orders

`POST /orders/{order_id}/retry` — re-process a failed order from scratch. Clears existing traces and enqueues a new Celery chain.

### 9.4 Retrieval Relevance Logging

For every RAG call, log which chunks were returned, their vector/keyword/fused scores, and the retrieval latency. Display "Show source chunks" in the frontend trace step with a dropdown showing the actual chunk text and scores.

---

## 10. Project Structure

```
bm_build/
├── docker-compose.yml
├── .env.example
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app
│   │   ├── celery_app.py            # Celery app
│   │   ├── config.py                # Pydantic Settings
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── orders.py
│   │   │   ├── documents.py
│   │   │   └── errors.py
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── orchestrator.py
│   │   │   ├── retriever.py
│   │   │   ├── worker.py
│   │   │   └── verifier.py
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── models.py
│   │   │   ├── model_router.py
│   │   │   └── cost_tracker.py
│   │   ├── rag/
│   │   │   ├── __init__.py
│   │   │   ├── chunker.py
│   │   │   ├── embedding.py
│   │   │   ├── retriever.py
│   │   │   ├── rewriter.py
│   │   │   ├── multi_query.py
│   │   │   └── reranker.py
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── session.py
│   │   │   └── models.py
│   │   └── cache/
│   │       ├── __init__.py
│   │       └── redis.py
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── conftest.py
│   │   ├── test_agents.py
│   │   ├── test_rag.py
│   │   └── test_integration.py
│   └── scripts/
│       └── seed_documents.py
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── next.config.js
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                 # Home / submit form
│   │   ├── globals.css
│   │   └── orders/
│   │       ├── page.tsx             # Order list (optional redirect)
│   │       └── [id]/
│   │           └── page.tsx         # Order detail + trace
│   ├── components/
│   │   ├── OrderForm.tsx
│   │   ├── OrderList.tsx
│   │   ├── StatusBadge.tsx
│   │   ├── AgentTrace.tsx
│   │   ├── TraceStep.tsx
│   │   ├── RetrievedChunks.tsx
│   │   ├── CostBar.tsx
│   │   └── ErrorAlert.tsx
│   ├── store/
│   │   └── orders.ts
│   └── lib/
│       ├── sse.ts
│       └── api.ts
│
└── deliverables/
    ├── README.md
    ├── ARCHITECTURE.md
    └── DECISIONS.md
```

---

## Appendix: Key Design Principles

1. **No god-functions**: Every component has a single responsibility with typed contracts.
2. **Fail explicitly**: All errors are structured with machine-readable codes. No silent failures.
3. **Observability-first**: Every agent step is logged with latency, cost, model, and cache status.
4. **Cost-aware**: The system tracks spending per order and gracefully degrades when budget is exceeded.
5. **Idempotent by design**: POST /orders supports Idempotency-Key to prevent duplicate processing.
6. **Graceful degradation**: LLM API failures fall back to alternative models; budget exhaustion falls back to cheap tier.
7. **Configurable**: LLM provider, model tiers, cost ceiling, and step budget are all environment-configurable.

---

*End of Plan — Ready for Implementation*
