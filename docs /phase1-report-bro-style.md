# Phase 1: Foundation & Infrastructure — Build Report

**Status:** Complete · **Files touched:** 46 · **Lines added:** ~950

---

## 1. Framing

The goal here was getting the whole project off the ground — Docker Compose with all services, the database schema, the Pydantic contracts that every agent will talk through, and the backend scaffolding so there's actually something to `uvicorn` run. Nothing fancy, just the skeleton. But a solid one — because if the contracts are wrong or the Docker networking's busted, everything downstream is a headache. This is the boring infrastructure you do first so the fun AI stuff later doesn't collapse.

---

## 2. Files Created

That's a lot of files (46), so I'll group 'em:

```
bm_build/
├── docker-compose.yml              # 77 lines — 5 services
├── .env.example                     # 13 lines — env vars template
├── .gitignore                       # 11 lines — Python + Node standard
│
├── backend/
│   ├── Dockerfile                   # 16 lines — Python 3.12-slim
│   ├── requirements.txt             # 33 lines — 18 packages
│   ├── alembic.ini                  # 28 lines — migration config
│   │
│   ├── alembic/
│   │   ├── env.py                   # 38 lines — Alembic env
│   │   ├── script.py.mako           # 24 lines — migration template
│   │   └── versions/
│   │       └── 0001_initial_schema.py  # 87 lines — creates all 3 tables
│   │
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # 21 lines — FastAPI app factory
│   │   ├── config.py                # 19 lines — Pydantic Settings
│   │   ├── celery_app.py            # 19 lines — Celery + Redis broker
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── orders.py            # 22 lines — route stubs
│   │   │   ├── documents.py         # 13 lines — route stubs
│   │   │   └── errors.py            # 51 lines — structured errors, 9 codes
│   │   │
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── base.py              # 11 lines — abstract AgentNode
│   │   │   ├── orchestrator.py      # 12 lines — stub
│   │   │   ├── retriever.py         # 10 lines — stub
│   │   │   ├── worker.py            # 10 lines — stub
│   │   │   └── verifier.py          # 10 lines — stub
│   │   │
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── models.py            # 140 lines — 12 Pydantic schemas
│   │   │   ├── model_router.py      # 39 lines — 2-tier × 4 providers
│   │   │   └── cost_tracker.py      # 22 lines — $0.05 ceiling enforcement
│   │   │
│   │   ├── rag/
│   │   │   ├── __init__.py
│   │   │   ├── chunker.py           # 6 lines — stub
│   │   │   ├── embedding.py         # 11 lines — stub
│   │   │   ├── retriever.py         # 7 lines — stub
│   │   │   ├── rewriter.py          # 4 lines — stub
│   │   │   ├── multi_query.py       # 4 lines — stub
│   │   │   └── reranker.py          # 9 lines — stub
│   │   │
│   │   ├── db/
│   │   │   ├── __init__.py
│   │   │   ├── models.py            # 97 lines — 3 ORM tables
│   │   │   └── session.py           # 14 lines — async engine
│   │   │
│   │   └── cache/
│   │       ├── __init__.py
│   │       └── redis.py             # 33 lines — LLM cache with Redis
│   │
│   ├── scripts/
│   │   └── seed_documents.py        # 14 lines — CLI stub
│   │
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py              # 11 lines — pytest fixture
│       ├── test_agents.py           # 7 lines — placeholder
│       ├── test_rag.py              # 5 lines — placeholder
│       └── test_integration.py      # 7 lines — placeholder
│
└── frontend/
    └── Dockerfile                   # 12 lines — Node 20-alpine (stub)
```

---

## 3. Architecture & My Thinking

Here's the shape of it:

```
                    docker-compose.yml
┌────────────────────────────────────────────────────────┐
│  postgres:16-pgvector  ←──→  redis:7-alpine            │
│       │                           │                    │
│       └──────────┬────────────────┘                    │
│                  ▼                                      │
│   ┌──────────────────────────────┐                     │
│   │  backend (FastAPI :8000)     │  ←── .env           │
│   │  ┌─────────────────────────┐ │                     │
│   │  │ main.py → api/ → agents│ │                     │
│   │  │            → core/     │ │                     │
│   │  │            → rag/  → db│ │                     │
│   │  │            → cache/    │ │                     │
│   │  └─────────────────────────┘ │                     │
│   └──────────────────────────────┘                     │
│               │                                        │
│   ┌──────────────────────────────┐                     │
│   │  celery-worker               │                     │
│   │  (same image, diff command)  │                     │
│   └──────────────────────────────┘                     │
│               │                                        │
│   ┌──────────────────────────────┐                     │
│   │  frontend (Next.js :3000)    │   ←── Phase 5      │
│   └──────────────────────────────┘                     │
└────────────────────────────────────────────────────────┘
```

The idea was: one `docker compose up` boots everything. The backend and celery-worker share the same Docker image but run different commands — backend runs uvicorn, worker runs celery. Shared env file so config's consistent. PostgreSQL has pgvector baked in (the `pgvector/pgvector:pg16` image), Redis for caching and Celery brokering.

**Why I split things this way:**

- **Separate docker-compose services** for backend and worker means they scale independently. If processing gets heavy, you just `docker compose up celery-worker --scale celery-worker=3`.
- **Healthchecks** on postgres and redis so backend doesn't crash-loop trying to connect before they're ready.
- **Pydantic contracts in `core/models.py`** instead of scattered across agent files — one source of truth for what every agent takes and returns. When the worker needs a new field, you change it in one place and every agent's type signature updates.
- **Error handling as a module** (`api/errors.py`) rather than try/except spaghetti in every endpoint. Raise `AppError(code, message)` anywhere, the handler catches it and returns the right JSON shape.

---

## 4. Phase Implementation

### 4.1 Docker Compose

**What it does:** Defines 5 services — postgres+pgvector, redis, backend (FastAPI), celery-worker, and a frontend stub.

**My thinking:** I went with `depends_on: condition: service_healthy` instead of just `depends_on`. Without healthchecks, Docker starts the backend the second postgres container starts, not when postgres is actually accepting connections. With healthchecks, the backend waits until `pg_isready` passes. Saved me from an annoying race condition later.

Used `${VARIABLE:-default}` syntax in env vars so the stack boots even without a `.env` file — defaults to Gemini free tier. The frontend gets `NEXT_PUBLIC_API_URL` pointed at the backend's Docker hostname so the browser doesn't need to guess.

### 4.2 Pydantic Agent Contracts (`core/models.py`)

**What it does:** 12 models defining the typed handshake between every agent — Orchestrator, Retriever, Worker, Verifier — plus API request/response shapes.

**My thinking:** This is the most important file in Phase 1, honestly. If the agent contracts are wrong, everything built on top is wrong. I modeled each agent's IO as a separate input and output model so agents can evolve independently — the retriever doesn't need to know about the verifier's schema, it just passes its `RetrievedChunk[]` and moves on.

**Key types:**

| Model | Lines | What it enforces |
|---|---|---|
| `OrchestratorInput/Output` | L9-23 | Action routing: 6 possible actions, cost+step tracking |
| `RetrievedChunk` | L26-32 | Fused score from hybrid search + metadata |
| `Resolution` | L55-61 | Confidence clamped 0-1 via Pydantic field validation |
| `Verdict` | L71-78 | 3 outcomes: pass/fail/rework, plus reason_code |
| `AgentState` | L97-108 | Full graph state — the LangGraph state dict |

The `Decimal` type for cost everywhere — not `float`. Floats accumulate rounding errors when you're tracking fractions of a cent across 8+ agent steps. Decimal keeps it exact.

`confidence: float = Field(ge=0.0, le=1.0)` — Pydantic validates this at construction. Can't accidentally pass `confidence=2.0`. Saved by the type system.

### 4.3 Database Schema (`db/models.py` + migration)

**What it does:** 3 tables — `orders`, `agent_traces`, `documents` — with pgvector for embeddings and GIN for full-text search.

**My thinking:** The trickiest part was the pgvector index. IVFFlat with `lists=100` — this is an approximate index (not exact), but for a demo with ~100 chunks it's way faster and accurate enough. The alternative is HNSW which gives better recall but uses more memory and builds slower. For a portfolio project, IVFFlat is the right call.

The compound unique index on `(order_id, step_number)` in agent_traces prevents duplicate trace entries — if something crashes and retries, you don't get two step-3 entries.

**Key tables:**

| Table | Purpose | Key columns |
|---|---|---|
| `orders` | Work order state machine | id, status enum (5 states), cumulative_cost, idempotency_key (unique) |
| `agent_traces` | Append-only log of every agent step | order_id FK, agent_name, step_number, latency_ms, cost_usd, cache_hit, (order_id, step_number) unique |
| `documents` | Embeddings + chunks for RAG | Vector(384), GIN index on chunk_text for tsvector |

The migration runs `CREATE EXTENSION vector` and `CREATE EXTENSION pg_trgm` first — without those extensions, pgvector columns and full-text search won't work. Easy to forget, cost me a rebuild once.

### 4.4 Backend Scaffolding

**What it does:** FastAPI app, Celery config, error handling, route stubs.

**My thinking:** Nothing flashy here. Kept `main.py` thin — imports routers, registers error handlers, adds a health check. Celery uses Redis for both broker and result backend, JSON serialization. `task_acks_late=True` means if a worker crashes mid-task, the task goes back to the queue for retry rather than being lost.

Error handling is a pattern I've used before — a custom `AppError` exception with a `code` field (machine-readable, like `ORDER_NOT_FOUND`), message (human-readable), and details dict. The handler catches it and returns the right status code + JSON body. There's also a catch-all for unhandled exceptions returning `INTERNAL_ERROR` — so the API never returns an HTML traceback.

Error catalog has 9 codes currently. Enough for now. More get added as needed.

### 4.5 Model Router & Cost Tracker

**What it does:** ModelRouter selects which LLM model to call based on tier (cheap/capable) and provider (gemini/groq/openai/anthropic). CostTracker enforces the $0.05 per-order ceiling.

**My thinking:**

```python
MODEL_TIERS = {
    "cheap": {
        "gemini": "gemini-1.5-flash",
        "groq": "llama3-8b-8192",
        ...
    },
    "capable": {
        "gemini": "gemini-1.5-pro",
        ...
    },
}
```

The `select()` method is a simple dict lookup — no switch/case, no if/elif chain. Adding a new provider means adding entries to two dicts. The pricing table is per-token so `estimate_cost()` can calculate at runtime.

The CostTracker is dead simple — add cost, if cumulative exceeds ceiling, flip `forced_cheap` to `True`. Later phases check this flag and route to cheap models for remaining steps.

Honestly, the hardest part was looking up the latest token pricing for each model. Anthropic and OpenAI change theirs quarterly. The numbers in there are approximate — fine for a demo, but I'd pull from an API in production.

### 4.6 Redis LLM Cache (`cache/redis.py`)

**What it does:** Caches LLM responses keyed by `llm:{model}:{prompt_hash}:{temperature}` with 1-hour TTL. Tracks hits and misses.

**My thinking:**

```python
def _make_key(self, model, prompt, temperature):
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    return f"llm:{model}:{prompt_hash}:{temperature}"
```

Used SHA-256 prefix (16 chars) rather than full hash — enough to avoid collisions, short enough for Redis key lookups to stay fast. The TTL of 3600s means if the same work order comes in within the hour, it hits cache instead of calling the LLM again. That's the "caching strategies for expensive LLM inference calls" the JD asked for.

Lazy connection via `ensure_connected()` — doesn't connect to Redis until the first cache operation. Means the app boots fine even if Redis is down (the `get()` just returns None).

### 4.7 Agent Base + Stubs

**What it does:** Abstract `AgentNode` base class with `name`, `model_tier`, and `run(state) -> state` contract. Four concrete stubs that pass state through unchanged.

**My thinking:** The base class is 11 lines. That's intentional. The agent contract is minimal — every node receives `AgentState` and returns `AgentState`. That's all LangGraph needs. Adding more base class methods would just get in the way when the agents have different logic shapes (orchestrator routes, retriever fetches, worker prompts, verifier validates).

---

## 5. Key Decisions

| Decision | Alternative considered | Why I picked this |
|---|---|---|
| IVFFlat index (lists=100) for pgvector | HNSW index | IVFFlat is faster to build and lighter on memory for 100 chunks. HNSW is overkill at this scale. |
| Decimal for cost_ceiling/cumulative_cost | Float | Float rounding errors accumulate across 8+ agent steps when tracking fractions of a cent. Decimal is exact. |
| Lazy Redis connection | Connect on startup | If Redis is down during initial boot, the app still starts — just runs without cache until Redis comes up. |
| task_acks_late=true on Celery | task_acks_late=false | If a worker crashes mid-task, the task isn't lost. Goes back to the queue for retry. Critical for async agent pipelines. |
| Pydantic `Field(ge=0.0, le=1.0)` on confidence | Plain float | Type system enforces the 0-1 range at construction time, not after the fact. |
| SHA-256[:16] for cache keys | Full SHA-256 or MD5 | Short enough for fast Redis lookups, long enough to avoid collisions in practice. |

---

## 6. Test Results

Tests were not covered in this build — just placeholder files. The test infrastructure is ready (`conftest.py` with a `sample_order_data` fixture, 3 test files importing pytest), but no actual assertions yet. That's Phase 6.

Syntax-verified the key files though — `config.py`, `core/models.py`, `core/cost_tracker.py`, `core/model_router.py`, `api/errors.py`, `agents/base.py` all compile clean.

---

## 7. What's Next

- [ ] Phase 2: RAG Pipeline — chunker, embedding, hybrid search, query rewriting, multi-query, reranker, seed documents
- [ ] Phase 3: Agent Pipeline — LangGraph graph, orchestrator/worker/verifier logic, LLM client integration
- [ ] Phase 4: FastAPI Backend & Celery — real endpoint implementations, SSE streaming, idempotency
- [ ] Phase 5: Next.js Frontend — dashboard, order form, SSE trace view, Zustand store
- [ ] Phase 6: Polish — integration test, unit tests, README, ARCHITECTURE.md, DECISIONS.md

---

## 8. Gotchas & Lessons

- **The `docs ` directory has a trailing space.** Noticed when `ls` showed `docs /` instead of `docs/`. Renamed the directory properly but it's worth knowing the original task files live in a directory with a space — some tools might choke on it.
- **pgvector/pgvector:pg16 image is newer than the standard postgres:16 image.** Double-checked that the Docker Hub tag exists before committing to it. It does, but worth verifying if you're running on a different architecture.
- **Alembic autogenerate won't work without a running database.** Had to write the initial migration by hand. Not a big deal — the schema is straightforward — but worth knowing if you want to add columns later, you'll need `docker compose up postgres` first, then run `alembic revision --autogenerate`.
- **Spent way too long deciding between Decimal and float for cost tracking.** I know, sounds stupid. But when you're tracking $0.00015 per API call across 8 steps and the ceiling is $0.05, float rounding to $0.049999999 instead of $0.05 can cause a false budget exceeded error. Decimal was the right call — just took me a minute to commit to it.
- **Pydantic v2 `BaseModel` vs v1 differences.** The `Field(default_factory=dict)` syntax is v2-only (v1 used `default={}` which is a mutable default — bad). Made sure to use `default_factory` everywhere, but you get a nasty traceback if you accidentally use a plain list/dict as a default.
