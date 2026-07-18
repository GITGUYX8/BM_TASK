# Work Order Processing System

A multi-agent pipeline that processes work orders using RAG-augmented LLM reasoning. The system ingests a work order, retrieves relevant context from a vector store, classifies and resolves the order via an agent chain, verifies the result, and streams the decision trace in real-time.

## Architecture

```
POST /orders → Celery chain → Orchestrator → RAG Retriever → Worker → Verifier → complete/fail/escalate
                                    ↑                                          |
                                    └──────────── rework/fail loop ────────────┘
```

```
                                  ┌─────────────┐
                                  │   Frontend   │  Next.js (App Router)
                                  │  localhost   │
                                  └──────┬──────┘
                                         │ HTTP / SSE
                                  ┌──────┴──────┐
                                  │   FastAPI    │  Backend API
                                  └──────┬──────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
              ┌─────┴─────┐      ┌──────┴──────┐      ┌─────┴─────┐
              │ PostgreSQL │      │    Redis    │      │  Celery   │
              │ + pgvector │      │  cache/rate │      │  workers  │
              └────────────┘      └─────────────┘      └───────────┘
```

### Multi-Agent Pipeline

| Agent | Responsibility |
|---|---|
| **Orchestrator** | Receives work order, routes to agents, manages state, enforces cost and step budgets |
| **RAG Retriever** | Retrieves relevant context from pgvector using hybrid search |
| **Worker** | Resolves the work order using LLM + RAG context, outputs structured resolution |
| **Verifier** | Validates worker output against business rules; overrules worker on failure |

Every agent declares a typed contract (Pydantic schema) for its input and output.

### RAG Pipeline

- **Chunking:** Recursive character splitting with configurable chunk size (500–1500 tokens) and overlap
- **Embedding:** Configurable embedding model (OpenAI, Cohere, or SentenceTransformers)
- **Hybrid search:** pgvector `<=>` (cosine distance) + PostgreSQL `tsvector`/`tsquery` full-text search with weighted fusion
- **Query rewriting:** Work orders are rewritten into search-optimized queries before retrieval
- **Multi-query:** 2–3 query variants generated, retrieved in parallel, results deduplicated
- **Reranking:** Retrieved chunks reranked by relevance before passing to the worker

### Backend API (FastAPI)

| Endpoint | Purpose |
|---|---|
| `POST /orders` | Submit a work order → enqueues async Celery processing |
| `GET /orders/:id` | Order status + full agent trace (every step with input/output/latency/cost) |
| `GET /orders/:id/stream` | SSE endpoint: streams each agent step as it completes |
| `POST /documents` | Ingest a document into the RAG store |
| `GET /docs` | OpenAPI auto-generated docs |

All endpoints return structured errors with machine-readable codes. `POST /orders` supports idempotency via `Idempotency-Key` header.

### LLM Cost Management

- **Cost ceiling:** $0.05 per work order. If exceeded, falls back to the cheap model tier.
- **Model router:** Two tiers — cheap/fast (classifications, verifier) and capable (complex reasoning, worker)
- **Redis cache:** LLM responses cached by (model, prompt_hash, temperature) with 1-hour TTL; cache hit/miss logged per order

### Observability

Every work order produces an **agent trace** — an append-only log of every agent step:

```
order_id, agent_name, step_number, input_summary, output_summary,
latency_ms, cost_usd, confidence, status (ok/retry/failed/escalated), cache_hit
```

Traces are queryable via `GET /orders/:id` and displayed in the frontend timeline.

## Stack

| Layer | Technology |
|---|---|
| Frontend | TypeScript, React, Next.js (App Router) |
| State | Zustand |
| Streaming | Server-Sent Events |
| Backend | Python — FastAPI |
| Async queue | Celery |
| Database | PostgreSQL + pgvector |
| Cache | Redis |
| LLM | Gemini / OpenAI / Anthropic / Groq |
| Structured output | Pydantic / Instructor library |
| Agents | Custom (no framework) |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- An LLM API key (Gemini, OpenAI, Anthropic, or Groq)

### Setup

```bash
# Clone and enter the project
git clone <repo-url> && cd bm_build

# Configure your LLM API key
cp .env.example .env
# Edit .env: set LLM_PROVIDER and LLM_API_KEY

# Start everything
docker compose up --build
```

### Seed Data

Once services are running, seed the RAG store with demo documents:

```bash
docker compose exec backend python -m app.rag.seed_data
```

### Trigger a Demo

```bash
curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"title": "Network outage in sector 7G", "description": "Users in building 7G report intermittent connectivity since 14:00 UTC. Affects ~200 workstations on VLAN 42.", "priority": "high"}'

# Check status + agent trace
curl http://localhost:8000/orders/<order_id>

# Stream trace in real-time
curl -N http://localhost:8000/orders/<order_id>/stream
```

Or open `http://localhost:3000` for the web UI.

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── agents/        # Orchestrator, Retriever, Worker, Verifier
│   │   ├── api/           # FastAPI routes (orders, documents)
│   │   ├── cache/         # Redis LLM cache
│   │   ├── core/          # Models, model router, cost tracker
│   │   ├── db/            # SQLAlchemy models, session
│   │   └── rag/           # Chunker, embedder, retriever, rewriter, reranker
│   ├── alembic/           # Database migrations
│   ├── tests/             # Integration & unit tests
│   └── Dockerfile
├── frontend/              # Next.js web UI
├── docker-compose.yml
└── .env.example
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini`, `openai`, `anthropic`, or `groq` |
| `LLM_API_KEY` | — | Your LLM API key |
| `COST_CEILING` | `0.05` | Max LLM cost per order (USD) |
| `MAX_STEPS` | `8` | Max agent turns per order |
| `DATABASE_URL` | `postgresql+asyncpg://app:app@localhost:5432/workorders` | Postgres connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |

## Testing

```bash
# Backend tests (runs against a test DB, needs services up)
docker compose exec backend pytest

# Tests cover:
# - Agent contracts (Pydantic validation)
# - RAG pipeline (chunking, hybrid search, reranking)
# - Full integration (submit → agents → RAG → trace)
```
