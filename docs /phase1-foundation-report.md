# Phase 1 — Foundation & Infrastructure: Implementation Report

**Date:** 2026-07-15  
**Plan Reference:** `PLAN.md` Section 3  
**Estimated Time:** 2.5 hours (actual)  

---

## Overview

Phase 1 establishes the entire project skeleton: Docker Compose orchestration, PostgreSQL schema with pgvector, Pydantic agent contracts, backend scaffolding with FastAPI + Celery, Alembic migrations, and the project directory structure. Every file compiles and imports cleanly.

---

## Files Created (47 total)

### 1. Docker Compose (`docker-compose.yml`)

5 services defined:

| Service | Image | Port | Purpose |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | PostgreSQL + vector extension |
| `redis` | `redis:7-alpine` | 6379 | Cache, Celery broker, rate limiter |
| `backend` | `./backend/Dockerfile` | 8000 | FastAPI app (with hot-reload) |
| `celery-worker` | `./backend/Dockerfile` | — | Celery worker (concurrency=2) |
| `frontend` | `./frontend/Dockerfile` | 3000 | Next.js UI (TODO: Phase 5) |

Key decisions:
- `depends_on` with `condition: service_healthy` ensures postgres/redis are ready before backend starts
- Healthchecks on postgres (`pg_isready`) and redis (`redis-cli ping`)
- All services share `.env` file for consistent config
- Celery uses the same image as backend with different `command`

### 2. Backend Scaffolding (`backend/app/`)

**Entry point:** `main.py`
- FastAPI app with title "Work Order Processing System", version `0.1.0`
- Routes: `/api/orders`, `/api/documents`, `/api/health`, `/docs`
- Structured error handlers registered via `register_error_handlers()`

**Configuration:** `config.py`
- Pydantic `BaseSettings` reading from `.env`:
  - `DATABASE_URL`, `REDIS_URL`, `LLM_PROVIDER`, `LLM_API_KEY`
  - `COST_CEILING` (default $0.05), `MAX_STEPS` (default 8)
  - `MAX_RETRIES` (2), `RETRY_DELAY` (5s)

**Celery:** `celery_app.py`
- Broker + backend both point to Redis
- Serialization: JSON
- Settings: `task_acks_late=True`, `worker_prefetch_multiplier=1`

**API Layer:**
- `api/orders.py` — stubs for `GET /orders`, `POST /orders`, `GET /orders/:id`, `GET /orders/:id/stream`
- `api/documents.py` — stub for `POST /documents`
- `api/errors.py` — `AppError` exception class, error handler registration, error catalog with 9 codes:
  - `ORDER_NOT_FOUND` (404), `VALIDATION_ERROR` (422), `BUDGET_EXCEEDED` (402), `LLM_API_ERROR` (502), etc.

### 3. Pydantic Agent Contracts (`core/models.py`)

12 models defining typed contracts between agents:

| Model | Fields | Used By |
|---|---|---|
| `OrchestratorInput` | order_id, title, description, priority, cumulative_cost, step_count | Orchestrator entry |
| `OrchestratorOutput` | action (6 literals), next_agent, reason, cost, step_count | Orchestrator exit |
| `RetrievedChunk` | document_title, chunk_text, vector/keyword/fused_score, metadata | RAG output |
| `RetrieverQuery` | order_id, raw_query, rewritten_query, variants | RAG input |
| `RetrieverResult` | order_id, chunks[], latency_ms | RAG output |
| `WorkerInput` | order_id, description, chunks[], model_tier | Worker input |
| `Resolution` | resolution_summary, confidence (0-1), actions_taken[], model, cost | Worker output |
| `VerifierInput` | order_id, original_order, resolution, model_tier | Verifier input |
| `Verdict` | result (pass/fail/rework), reason_code, explanation, confidence, model, cost | Verifier output |
| `AgentTraceEntry` | Full trace: agent_name, step_number, latency, cost, confidence, status, cache_hit | Observability |
| `AgentState` | Full graph state: order, traces[], current_step, cumulative_cost, chunks[], resolution, verdict, rework_count, status | LangGraph state |
| `OrderCreate` / `OrderResponse` | API request/response shapes | API layer |
| `DocumentCreate` / `DocumentResponse` | Document ingestion shapes | API layer |

### 4. Supporting Core Modules

**`core/model_router.py`**
- 2-tier model selection (cheap/capable) across 4 providers:
  - Cheap: Gemini Flash, Llama 3 8B, GPT-4o-mini, Claude Haiku
  - Capable: Gemini Pro, Llama 3 70B, GPT-4o, Claude Sonnet
- `estimate_cost()` based on per-model token pricing

**`core/cost_tracker.py`**
- Tracks `cumulative_cost` against configurable ceiling ($0.05 default)
- Auto-switches to `forced_cheap` mode when ceiling exceeded
- `remaining_budget()` for UI display

### 5. Database Layer

**`db/models.py`** — SQLAlchemy ORM (async):

- **`Order`** table: id (UUID PK), title, description, priority (enum), status (enum), idempotency_key (unique), cumulative_cost (Numeric 8,6), step_count, error_trace (JSONB), timestamps
- **`AgentTrace`** table: id (UUID PK), order_id (FK→orders), agent_name, step_number, input_hash, input/output_summary, output_json (JSONB), latency_ms, cost_usd, confidence, status (enum), model_used, cache_hit, created_at. Indexes on `order_id` and `(order_id, step_number)` unique.
- **`DocumentChunk`** table: id (UUID PK), title, content, chunk_index, chunk_text, embedding (Vector 384), metadata (JSONB), created_at. IVFFlat index on embedding for cosine search, GIN index on chunk_text for full-text search.

**`db/session.py`** — Async SQLAlchemy engine with `async_sessionmaker`.

### 6. Alembic Migrations

**`alembic.ini`** + **`alembic/env.py`** + **`alembic/script.py.mako`**

**Migration `0001_initial_schema.py`:**
- Enables `vector` and `pg_trgm` extensions
- Creates `orders`, `agent_traces`, `documents` tables
- Creates IVFFlat index on `documents.embedding` (vector_cosine_ops, 100 lists)
- Creates GIN index on `documents.chunk_text` for `to_tsvector` full-text search
- Defines enums: `OrderPriority`, `OrderStatus`, `TraceStatus`
- Proper downgrade path drops tables and types

### 7. Agent Stubs

**`agents/base.py`** — Abstract `AgentNode` class with `name`, `model_tier`, and `run(state) -> state` contract.

Stub implementations for all 4 agents (orchestrator, retriever, worker, verifier) that pass state through unchanged.

### 8. RAG Stubs

Placeholder files for all RAG pipeline components:
- `chunker.py`, `embedding.py`, `retriever.py`, `rewriter.py`, `multi_query.py`, `reranker.py`

### 9. Cache Module

**`cache/redis.py`** — `LLMCache` class:
- Key format: `llm:{model}:{sha256_prompt_16chars}:{temperature}`
- TTL: 3600s (1 hour)
- Tracks cache hits/misses via Redis counters (`stats:cache_hits`, `stats:cache_misses`)
- Uses `redis.asyncio` for non-blocking operations

### 10. Docker & Config

- `backend/Dockerfile`: Python 3.12-slim, installs requirements + dev packages
- `frontend/Dockerfile`: Node 20-alpine (stub, filled in Phase 5)
- `backend/requirements.txt`: 18 packages (fastapi, sqlalchemy[asyncio], asyncpg, pgvector, celery[redis], instructor, sentence-transformers, pytest, etc.)
- `.env.example`: All config vars documented with defaults
- `.gitignore`: Python + Node standard ignores

### 11. Test Scaffolding

`tests/conftest.py`, `test_agents.py`, `test_rag.py`, `test_integration.py` — all with placeholder tests, ready for Phase 6.

---

## Architecture Diagram (Phase 1 Scope)

```
┌─────────────────────────────────────────────────────────────┐
│                      docker-compose.yml                      │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ postgres  │  │  redis   │  │ backend  │  │ celery-     │ │
│  │ :5432     │  │ :6379    │  │ :8000    │  │ worker      │ │
│  │ pgvector  │  │ cache/   │  │ FastAPI  │  │             │ │
│  │           │  │ broker   │  │          │  │ agents      │ │
│  └─────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘ │
│        │              │             │                │       │
│        └──────────────┴─────────────┴────────────────┘       │
│                          depends_on                          │
│                                                             │
│  ┌──────────┐                                                │
│  │ frontend │                                                │
│  │ :3000    │                                                │
│  │ Next.js  │   (stub — Phase 5)                             │
│  └──────────┘                                                │
└─────────────────────────────────────────────────────────────┘

Backend Internal:
┌─────────────────────────────────────────────────────┐
│  backend/app/                                       │
│  ├── main.py              FastAPI app factory       │
│  ├── config.py            Pydantic Settings          │
│  ├── celery_app.py        Celery instance            │
│  ├── api/                 Route handlers (stubs)     │
│  │   ├── orders.py        Order endpoints            │
│  │   ├── documents.py     Document endpoints         │
│  │   └── errors.py        Structured error handling  │
│  ├── agents/              Agent nodes (stubs)        │
│  │   └── base.py          Abstract AgentNode         │
│  ├── core/                Business logic             │
│  │   ├── models.py        12 Pydantic schemas        │
│  │   ├── model_router.py  2-tier × 4 providers      │
│  │   └── cost_tracker.py  $0.05 ceiling enforcement │
│  ├── rag/                 Pipeline stubs              │
│  ├── db/                  ORM + session              │
│  │   ├── models.py        3 tables (Order, Trace,    │
│  │   │                    DocumentChunk)             │
│  │   └── session.py       Async engine               │
│  └── cache/               LLM response cache         │
│      └── redis.py         Key: llm:{model}:{hash}    │
└─────────────────────────────────────────────────────┘
```

---

## Verify Commands

```bash
# Check imports work (requires deps installed)
cd backend && pip install -r requirements.txt && python -c "
from app.core.models import (
    OrchestratorInput, OrchestratorOutput, RetrieverResult,
    RetrievedChunk, WorkerInput, Resolution, VerifierInput,
    Verdict, AgentState, AgentTraceEntry, OrderCreate, DocumentCreate
)
from app.core.model_router import ModelRouter
from app.core.cost_tracker import CostTracker
from app.db.models import Base, Order, AgentTrace, DocumentChunk
from app.cache.redis import LLMCache
from app.agents.base import AgentNode
print('All imports OK')
"
```

```bash
# Run placeholder tests
cd backend && python -m pytest tests/ -v
```

---

## Next: Phase 2 — RAG Pipeline

Ready to implement:
1. `rag/chunker.py` — RecursiveCharacterTextSplitter (chunk_size=1000, overlap=200)
2. `rag/embedding.py` — SentenceTransformer `all-MiniLM-L6-v2`
3. `rag/retriever.py` — Hybrid search combining `<=>` vector + `tsvector` full-text
4. `rag/rewriter.py` — LLM-based query rewriting with few-shot prompt
5. `rag/multi_query.py` — 2–3 query variant generation
6. `rag/reranker.py` — Cross-encoder reranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`)
7. `scripts/seed_documents.py` — 12 IT support documents for demo

---

*End of Phase 1 Report*
