# Architecture — Work Order Processing System

Multi-agent pipeline that processes work orders using RAG-augmented LLM reasoning.
Submit via Next.js form → FastAPI enqueues Celery task → agent graph
(orchestrator → retriever → worker → verifier) → traces persisted to PostgreSQL
and streamed over SSE → timeline UI.

## Component diagram

```
                    ┌─────────────┐
                    │   Frontend   │  Next.js App Router (Zustand)
                    │  localhost   │
                    └──────┬──────┘
                           │ HTTP / SSE (EventSource)
                    ┌──────┴──────┐
                    │   FastAPI    │  (all routes under /api prefix)
                    │  backend:8000│  POST /api/orders, GET /api/orders/:id,
                    └──────┬──────┘  GET /api/orders/:id/stream, POST /api/documents,
                           │         POST /api/orders/:id/retry
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
  ┌─────┴─────┐      ┌─────┴─────┐      ┌─────┴─────┐
  │ PostgreSQL │      │   Redis   │      │  Celery   │
  │ + pgvector │      │ cache/pub │      │  workers  │
  │ orders,    │      │ sub/broker│      │ process_  │
  │ traces,    │      │           │      │ order     │
  │ documents  │      │           │      │           │
  └────────────┘      └───────────┘      └───────────┘
```

## Data flow

```
POST /api/orders (+ Idempotency-Key, token-bucket rate limit 30/min per IP → 429 RATE_LIMITED)
  → insert orders row (status=queued)
  → process_order.delay(order_id)          [Celery, Redis broker]
  → 201 { order_id } on create, 200 on idempotent replay

Celery worker: _process_order
  → status=processing
  → AgentGraph.run(state)                  [loop, max 8 steps]
       Orchestrator._decide → retrieve|resolve|verify|complete|fail|escalate
       retrieve → RetrieverNode → rag pipeline.retrieve()
                    rewrite → multi-query (2-3 variants) → hybrid search
                    → dedup → cross-encoder rerank → top-3 chunks
       resolve  → WorkerNode (capable tier) → Resolution(summary, confidence, actions)
       verify   → VerifierNode (cheap tier) → Verdict(pass|fail|rework)
       each step → on_trace → Redis PUBLISH order:{id}:traces + cost_tracker.add_cost
  → persist agent_traces rows, final status/cost/steps
  → retry ×2 on exception, else status=failed + error_trace + DLQ push (`dlq:orders`)

GET /api/orders?status=&limit=&offset=          → paginated list (default 50, max 100)
GET /api/metrics (root /metrics)               → Prometheus text: orders by status,
                                             traces total, cost total, cache
                                             hits/misses, celery depth, dlq depth

GET /api/orders/:id                            → order + full trace (DB)
GET /api/orders/:id/stream (SSE)               → Redis SUB order:{id}:traces
  event: step     — one AgentTraceEntry JSON per agent step (forwarded verbatim)
  event: complete — { order_id, status } on completed
  event: error    — { order_id, status } on failed/escalated
  event: done     — legacy alias for `complete` (kept for old clients)
  Termination is a fact, not an inference: the Celery task writes
  `order:{id}:done` (SETEX, 1h TTL) exactly once per terminal run, and the
  SSE handler reads it on every 1s poll tick. Retries clear the key on
  requeue so a stale marker can never end the new run's stream early.
  If the order is already terminal on connect, completion is emitted
  immediately from the DB status without subscribing.
GET /api/orders?status=escalated               → human-in-the-loop queue
POST /api/orders/:id/retry                     → failed/escalated only; clears traces,
                                              resets cost/steps, requeues Celery
POST /api/documents                            → chunk → embed → pgvector insert
```

## Agent contracts (`backend/app/core/models.py`)

| Model | Key fields |
|---|---|
| `OrchestratorInput` | order_id, title, description, priority, cumulative_cost, step_count |
| `OrchestratorOutput` | action (retrieve\|resolve\|verify\|complete\|escalate\|fail), reason |
| `RetrieverQuery` / `RetrieverResult` | raw/rewritten/variants → chunks[] + retrieval_latency_ms |
| `RetrievedChunk` | document_title, chunk_text, vector/keyword/fused_score, metadata |
| `WorkerInput` / `Resolution` | description + chunks → resolution_summary, confidence 0–1, actions_taken, model_used, cost_usd |
| `VerifierInput` / `Verdict` | order + resolution → result (pass\|fail\|rework), reason_code, explanation, confidence |
| `AgentTraceEntry` | agent_name, step_number, input/output_summary, output_json, latency_ms, cost_usd, confidence, status, model_used, cache_hit |
| `AgentState` | order, traces[], current_step, cumulative_cost, forced_cheap, chunks, resolution, verdict, rework_count, status, routing_key |
| `OrderCreate` / `OrderResponse` | API shapes; response carries full `traces[]` |

Rules enforced in code: orchestrator is rule-based (no LLM); worker uses capable
tier, verifier uses cheap tier; verifier overrules worker (fail/rework loops back,
never auto-completes); `max_steps=8` breaks loops; cost ceiling forces cheap tier.

## Technology choices

| Layer | Choice | Why |
|---|---|---|
| Backend | FastAPI (async) | JD requirement; native SSE via StreamingResponse |
| Queue | Celery + Redis broker | Retry semantics (max_retries=2), worker isolation; `asyncio.run` wrapper inside sync task |
| DB | PostgreSQL 16 + pgvector | Hybrid search: `<=>` cosine + `tsvector`/`tsquery` FTS with weighted fusion (0.7/0.3) |
| Cache | Redis, SHA256(model,prompt,temp)[:16], TTL 3600s | Idempotent LLM responses; hit/miss logged per trace; failures fall through. One client per process (PID-guarded lazy connect — never share a socket across Celery forks); the SSE subscriber keeps a dedicated connection per stream |
| Embeddings | SentenceTransformers `all-MiniLM-L6-v2` (384-dim) | Free, local, no key |
| Rerank | cross-encoder `ms-marco-MiniLM-L-6-v2` | Local, lightweight |
| Chunking | Recursive character splitter, 1000 tokens / 200 overlap | Inside required 500–1500 range |
| Frontend | Next.js 14 App Router + Zustand + native EventSource | JD requirement; two-phase load (GET stored traces → SSE live) |
| Agents | Raw loop (`agents/graph.py`), no LangGraph | 70-line loop is transparent, zero-dep, Python-3.14 safe |

## Database schema

- `orders`: id UUID PK, title, description, priority enum, status enum
  (queued/processing/completed/failed/escalated), `idempotency_key` unique nullable,
  cumulative_cost NUMERIC(8,6), step_count, error_trace JSONB, timestamps.
- `agent_traces`: id UUID PK, order_id FK, agent_name, step_number,
  input_hash/summaries, output_json JSONB, latency_ms, cost_usd, confidence,
  status enum (ok/retry/failed/escalated), model_used, cache_hit.
  Indexes on `(order_id)`, `(order_id, step_number)` (non-unique: orchestrator and
  executor may share a step number).
- `documents`: id UUID PK, title, content, chunk_index, chunk_text,
  embedding `vector(384)`, metadata JSONB. IVFFlat cosine index + GIN FTS index.

## Cost management

- Ceiling `$0.05`/order (`COST_CEILING`); `CostTracker` sets `forced_cheap` once
  breached; `AgentGraph` downgrades worker+verifier tiers; all costs `Decimal`.
- Model router: cheap (Gemini Flash / Llama3-8b / GPT-4o-mini / Haiku) vs capable
  (Gemini Pro / Llama3-70b / GPT-4o / Sonnet), selected by `LLM_PROVIDER`.
- No key configured → `llm_call` returns `None`; every agent degrades gracefully
  (template resolution, default pass verdict, no-op rewrite).

## Error model

All errors use the `{ "error": { "code", "message", "details" } }` envelope
(`api/errors.py` catalog): `ORDER_NOT_FOUND` 404, `ORDER_PROCESSING` 409,
`IDEMPOTENCY_MISMATCH` 409, `VALIDATION_ERROR` 422, `BUDGET_EXCEEDED` 402,
`LLM_API_ERROR` 502, `RATE_LIMITED` 429, `INTERNAL_ERROR` 500.
Frontend parses the envelope into typed `ApiError` and renders inline.
