# Phase 4 — Async Work Order Processor Pipeline — Build Report

**Status:** Complete · **Files touched:** 12 backend + 8 frontend · **Lines added:** ~1,200

---

## 1. Framing

Phase 4 took a synchronous, single-process work order processor and made it fully asynchronous — Celery for background task queuing, Redis pub/sub for real-time SSE streaming, an LLM response cache to avoid redundant API calls, and a cost-enforcement layer that proactively downgrades model tier when a per-order budget is exceeded. A Next.js frontend skeleton was added to submit orders and watch agent traces stream in live. The main constraint was that no API keys or .env config were available during development, so every LLM-dependent path had to degrade gracefully (no-op rewrite, template resolution, default pass verdict).

---

## 2. Files Created / Modified

### Backend (833 lines added across 12 files)

| File | Lines | Change | What it does |
|---|---|---|---|
| `app/tasks/process_order.py` | 87 | **NEW** | Celery task — deserializes order from DB, reconstructs `AgentState`, runs `AgentGraph`, persists traces, retries on failure |
| `app/cache/events.py` | 28 | **NEW** | `TracePublisher` / `TraceSubscriber` — Redis pub/sub wrappers for streaming traces |
| `app/core/cost_tracker.py` | 22 | **NEW** | `CostTracker` — cumulative cost ceiling with auto-downgrade flag |
| `app/cache/redis.py` | 33 | **MODIFIED** | `LLMCache` — SHA256-keyed Redis cache with 3600s TTL, hit/miss counters |
| `app/core/model_router.py` | 154 | **MODIFIED** | `ModelRouter.llm_call()` — checks cache before provider call, writes cache on response |
| `app/agents/graph.py` | 70 | **MODIFIED** | `AgentGraph` — accepts `on_trace` callback, instantiates `CostTracker`, enforces cheap tier after ceiling breached |
| `app/api/orders.py` | 105 | **MODIFIED** | Added `POST /orders` (enqueues Celery), `GET /orders/{id}/stream` (SSE endpoint) |
| `app/db/models.py` | 97 | **MODIFIED** | Removed unique constraint on `(order_id, step_number)` to allow orchestrator + executor sharing step numbers |
| `app/core/models.py` | 141 | **MODIFIED** | Minor additions to support trace streaming (no structural changes) |
| `tests/test_agents.py` | 189 | **MODIFIED** | 14 tests — orchestrator routing, worker/verifier fallbacks, graph full-flow, trace creation |
| `tests/test_rag.py` | 67 | **MODIFIED** | 10 tests — query rewriting, expansion, tsquery conversion, dedup, reranking |
| `tests/test_integration.py` | 6 | **MODIFIED** | Placeholder integration test |

### Frontend (~367 lines of source across 8 files)

| File | Lines | What it does |
|---|---|---|
| `package.json` | 21 | Next.js 14, React 18, Zustand 4, TypeScript 5 |
| `next.config.js` | 13 | API proxy rewrites `http://localhost:8000` |
| `tsconfig.json` | 21 | Strict TS config with `@/` path alias |
| `app/layout.tsx` | 23 | Root layout with nav (Home / Orders) |
| `app/page.tsx` | 16 | Home — OrderForm + OrderList side by side |
| `app/orders/page.tsx` | 10 | Full order list page |
| `app/orders/[id]/page.tsx` | 68 | Order detail — SSE live trace stream + timeline |
| `components/OrderForm.tsx` | 57 | Create order form (title, description, priority) |
| `components/OrderList.tsx` | 40 | Polled order list with status/priority/cost |
| `components/TraceTimeline.tsx` | 33 | Collapsible agent trace details |
| `lib/api.ts` | 56 | Fetch wrappers + `streamOrder()` EventSource |
| `lib/store.ts` | 22 | Zustand store for reactive order state |

### Infra

| File | Change |
|---|---|
| `docker-compose.yml` | Added `celery-worker` and `frontend` services |
| `frontend/Dockerfile` | Preexisting (Node 20 Alpine, `npm run dev`) |

---

## 3. Architecture & LLM Reasoning

The full data flow after Phase 4:

```
POST /orders → FastAPI → db insert → Celery delay(str(order_id))
                                              │
                                    ┌─────────┴──────────┐
                                    │  Celery Worker      │
                                    │  (async, retry×2)   │
                                    └─────────┬──────────┘
                                              │
                           AgentGraph.run(AgentState)
                           ┌──────────────────────┐
                           │  Orchestrator (cheap) │ ←── routing decision
                           └──────────┬───────────┘
                                      │
                    ┌─────────────────┼──────────────────┐
                    ▼                 ▼                  ▼
              Retriever           Worker           Verifier
           (hybrid search)    (resolve chunks)   (pass/fail/rework)
                    │                 │                  │
                    └─────────────────┴──────────────────┘
                                      │
                          on_trace → TracePublisher
                                      │
                               Redis PUBLISH channel
                                      │
                    ┌─────────────────┴──────────────────┐
                    ▼                                    ▼
              DB persist (commit)              SSE /orders/{id}/stream
                                               WebSocket-less streaming
                    │
                    ▼
              Frontend (Next.js)
              Zustand store → TraceTimeline
```

**LLM reasoning on the overall design:**

The LLM evaluated two approaches for the async queue: Celery vs. plain asyncio tasks with Redis. Celery won because it provides battle-tested retry semantics (max_retries, retry_delay), task tracking, and worker process management out of the box — things that would need to be reimplemented with raw Redis pub/sub and asyncio. The trade-off is added operational complexity (a separate worker process), but docker-compose already handled that.

For SSE streaming, the LLM considered WebSockets (socket.io, native ws) vs. Server-Sent Events. SSE was chosen because the data flow is unidirectional (server → client only), SSE is natively supported by browsers and EventSource, and it requires zero additional dependencies on the backend — just `StreamingResponse` with `text/event-stream`. The LLM recognized that WebSockets would be overkill for a trace-monitoring use case.

The cache layer uses SHA256 (truncated to 16 hex chars) as the cache key over full prompt hashing — a deliberate trade-off of collision risk (negligible at this scale) against key readability in Redis CLI. TTL of 3600s was chosen to match common LLM API rate-limit windows.

The cost tracker operates as a hard ceiling rather than a soft throttle — once `cumulative_cost > ceiling`, `forced_cheap` propagates to both the worker and verifier model tiers. The LLM considered a gradual throttle (e.g., switch to cheap after 80% of budget) but chose binary cutoff because the ceiling is small ($0.05) and gradual reduction would add state complexity without meaningful benefit.

---

## 4. Phase Implementation

### 4.1 LLM Cache (redis.py + model_router.py)

**What it does:** Before any LLM API call, checks Redis for a cached response keyed by `(model, sha256(prompt)[:16], temperature)`. On hit, returns cached text and sets `last_cache_hit = True`. On miss, calls the provider, writes the response to cache with 3600s TTL.

**LLM reasoning:** The LLM initially considered using the full SHA256 digest as the key, but shortened it to 16 hex characters for readability in Redis CLI debugging. The collision probability of a 64-bit hash over thousands of prompts is negligible. The cache set/get operations are wrapped in try/except so that a Redis outage doesn't crash the pipeline — it just falls through to a live API call. The LLM considered caching at the `AgentTraceEntry` level (deduplicating identical agent steps) but decided that was too granular and risked returning stale routing decisions.

**Key functions:**

| Function | Lines | Description |
|---|---|---|
| `LLMCache._make_key(model, prompt, temp)` | L16-18 | Truncated SHA256 key builder |
| `LLMCache.get(model, prompt, temp)` | L20-28 | Cache lookup with hit/miss stats increment |
| `LLMCache.set(model, prompt, temp, response)` | L30-33 | Write with 3600s TTL |
| `ModelRouter.llm_call(system, user, tier)` | L48-82 | Cache-check → provider call → cache-write flow |
| `_call_gemini` / `_call_openai` / `_call_anthropic` / `_call_groq` | L84-154 | Provider-specific HTTP clients |

**Edge cases handled:**
- No API key configured → returns `None` (no crash, no cache check)
- Cache unavailable (Redis down) → try/except, falls through to live call
- Provider returns non-200 → returns `None`, caller handles no-LLM fallback
- Cache write failure → silently ignored (response still returned to caller)

---

### 4.2 Cost Tracker (cost_tracker.py + graph.py)

**What it does:** `CostTracker` tracks cumulative LLM spend per order. When the ceiling (default $0.05) is exceeded, `forced_cheap` is set to `True`. The `AgentGraph.run()` loop checks this flag after each executor step and overrides `worker.model_tier` and `verifier.model_tier` to `"cheap"` if the budget is blown.

**LLM reasoning:** The LLM placed the `add_cost()` call after each executor step (retriever/worker/verifier) rather than the orchestrator step. The reasoning: the orchestrator uses the cheapest model tier by design and its routing decisions cost essentially nothing. The expensive calls are the executor agents that generate and verify resolutions — those are the ones that need cost policing. The LLM also propagated `forced_cheap` into `AgentState` so that the orchestrator can see it in subsequent routing cycles.

**Key functions:**

| Function | Lines | Description |
|---|---|---|
| `CostTracker.add_cost(cost)` | L12-15 | Accumulate cost, set forced_cheap if ceiling exceeded |
| `CostTracker.within_budget()` | L17-18 | Boolean check |
| `CostTracker.remaining_budget()` | L20-22 | Max(ceiling - cumulative, 0) |

**Edge cases handled:**
- Decimal precision: all costs are `Decimal` to avoid floating-point drift
- Zero-cost agents (orchestrator, no-LLM fallbacks) don't trigger the ceiling
- `forced_cheap` persists across rework cycles once set

---

### 4.3 Celery Task (celery_app.py + tasks/process_order.py + api/orders.py)

**What it does:** `POST /orders` creates the order in PostgreSQL with `status=queued`, then calls `process_order.delay(str(order_id))` and returns immediately. The Celery task `_process_order()` loads the order from DB, sets `status=processing`, runs `AgentGraph`, persists all traces, and sets the final status. On exception, it calls `task.retry()` (max 2 retries, 5s delay). The `GET /orders/{id}` endpoint loads order + traces from DB for polling clients.

**LLM reasoning:** The LLM faced a design choice: run the async event loop inside the Celery task or use Celery's native async support. The LLM chose `asyncio.run(_process_order(...))` inside the synchronous task because Celery's async support (via `async_task`) was still experimental in the version being used (Celery 5.x). The `asyncio.run()` wrapper is stable and the task is a single self-contained async function — there's no need for an async Celery worker pool.

The `on_trace` lambda is passed to `AgentGraph` which calls it after each agent step, publishing the trace to Redis before the task continues processing. This means the SSE endpoint can show traces before the Celery task is done — the streaming window overlaps with execution.

**Key functions:**

| Function | Lines | Description |
|---|---|---|
| `process_order(order_id_str)` | L16-20 | Celery task entry point, wraps async runner |
| `_process_order(order_id_str, task)` | L28-87 | Loads DB order, runs AgentGraph, persists results |
| `_publish_trace(order_id_str, trace)` | L23-25 | Publishes each trace dict to Redis |

**Edge cases handled:**
- Order not found in DB → returns silently, no retry
- Any exception during graph run → sets `OrderStatus.failed`, stores error trace, retries
- `asyncio.run()` in a sync Celery task — this works because the task function is called within an already-running event loop (Celery doesn't need one by default)

---

### 4.4 SSE Streaming (events.py + api/orders.py + graph.py)

**What it does:** `TracePublisher.publish(order_id, trace_data)` serializes the trace to JSON and publishes it to Redis channel `order:{id}:traces`. `GET /orders/{id}/stream` subscribes to that channel and yields SSE events as traces arrive. When a terminal trace is detected, sends `event: done` and closes.

**LLM reasoning:** The SSE endpoint needed to handle a subtle issue: if the order is already complete when the client connects, the Redis channel has no publisher. The LLM solved this by having the frontend first call `GET /orders/{id}` (which returns stored traces), then open the SSE connection for live updates. The `event_generator()` uses `pubsub.get_message(timeout=1.0)` with a polling loop rather than blocking forever — this allows detecting terminal conditions without waiting for a message.

The channel name pattern `order:{id}:traces` was chosen to be both human-readable in Redis CLI and namespaced to avoid collisions.

**Key functions:**

| Function | Lines | Description |
|---|---|---|
| `TracePublisher.publish(order_id, trace_data)` | L12-16 | Connects to Redis, publishes JSON, disconnects |
| `TraceSubscriber.subscribe(order_id)` | L23-28 | Connects to Redis, subscribes to channel, returns pubsub handle |
| `stream_order(order_id, session)` | L60-74 | SSE handler — subscribes, yields `data:` events, detects terminal traces |

**Edge cases handled:**
- Redis connection opened/closed per publish (not pooled) — safe for Celery's fork model
- Terminal detection: watches for output_json action or status field containing "complete"/"fail"/"escalate"
- `finally` block ensures `pubsub.unsubscribe()` + `redis.aclose()` on any exit path

---

### 4.5 Frontend Skeleton

**What it does:** A Next.js App Router application with three pages:
1. **Home** (`/`) — Order form + recent orders list
2. **Orders** (`/orders`) — Full order index
3. **Order detail** (`/orders/[id]`) — Live trace streaming via SSE

**LLM reasoning:** The LLM chose Next.js App Router over Pages Router per project convention. Zustand was chosen over Redux/Context for state management because the state shape is simple (list of orders + live traces) and Zustand avoids boilerplate. The API proxy in `next.config.js` rewrites `/api/*` to `http://localhost:8000/api/*` so both dev and production use the same path.

The SSE client in `[id]/page.tsx` uses native `EventSource` rather than a library (no external dependency). The LLM added a dedup check (`prev.some(t => t.step_number === trace.step_number && t.agent_name === trace.agent_name)`) because the initial `GET /orders/{id}` response includes all stored traces, and the SSE stream might redeliver the first trace if it arrives before the initial fetch completes.

**Key components:**

| Component | Lines | Description |
|---|---|---|
| `OrderForm` | 57 | Title/description/priority form, POSTs to `/api/orders` |
| `OrderList` | 40 | Polled list with status badges, cost, step count |
| `TraceTimeline` | 33 | Collapsible `<details>` per trace with agent name, status, latency, cost |
| `store.ts` | 22 | Zustand store: orders list, current order, live traces |

---

## 5. Key Decisions

| Decision | Alternative considered | LLM's reasoning |
|---|---|---|
| Celery over raw asyncio+Redis | In-process async task queue | Celery provides retry semantics, task tracking, worker process isolation. The operational cost of adding a worker container was zero (already using docker-compose). |
| SSE over WebSockets | socket.io, native WebSocket | Data flow is unidirectional (server → client). SSE is natively supported by EventSource with zero dependencies. WebSockets would add complexity for no benefit. |
| SHA256 truncated to 16 chars | Full hash, UUID, or incrementing counter | Truncation risk (collision) is negligible at this scale. Keys remain readable in Redis CLI. Counter-based keys would require state management. |
| Binary cost ceiling ($0.05) | Gradual throttle at 80% | The ceiling is small enough that gradual reduction adds complexity without meaningful benefit. `forced_cheap` is a simple boolean flag. |
| Async session per Celery task | Shared session pool | Celery workers fork — shared connections are unsafe. Each task opens/ closes its own async session. The trade-off is connection overhead, negligible at this scale. |
| Frontend first fetches GET then opens SSE | SSE-only | If the order is complete before the client connects, no traces would ever publish. The two-phase approach (GET stored traces → SSE for new ones) handles this cleanly. |

---

## 6. Test Results

- **`test_agents.py`**: 14 tests, all passing
  - 7 orchestrator tests (retrieve on fresh, complete on pass, fail on max retries, resolve on chunks, verify on resolution, escalate on error, trace appended)
  - 3 worker tests (fallback no LLM, fallback empty chunks, trace created)
  - 3 verifier tests (fail on no resolution, fallback no LLM, trace created)
  - 1 graph full-flow test (orchestrator routing with mocked session)
- **`test_rag.py`**: 10 tests, all passing
  - 6 RAG pipeline tests (rewrite, expand, dedup, rerank)
  - 4 parametrized tsquery conversion tests
- **`test_integration.py`**: 1 placeholder test (passing)
- **Edge case caught**: The worker fallback no-LLM test (`test_worker_fallback_no_llm`) confirmed that when `llm_api_key` is empty, the worker generates a template resolution with `confidence=0.1` rather than crashing.
- **Build verification**: Next.js production build compiles successfully with zero type errors.

---

## 7. What's Next

Potential future phases:

- [ ] **Phase 5: Error Recovery & Observability** — Structured error taxonomy, dead-letter queue for permanently failed orders, Prometheus/metrics endpoint for Celery queue depth and cache hit rates
- [ ] **Phase 6: Authentication & Multi-Tenant** — API key auth, order ownership, RBAC for agents
- [ ] **Phase 5 (alt): Frontend polish** — Tailwind CSS, pagination, real-time status badges, error states
- [ ] **Rate limiting** — Token bucket per API key on `POST /orders`
- [ ] **Docker Compose health** — Wait-for-it scripts so services start reliably in order

---

## 8. Gotchas & Lessons

- **`asyncio.run()` inside Celery tasks works but has a gotcha:** If the event loop is already running (e.g., running Celery with `--pool=gevent`), `asyncio.run()` raises `RuntimeError`. The LLM designed for the default prefork pool, which doesn't have this issue. If switching pool types, the task would need `asyncio.get_or_create_event_loop()` + `loop.run_until_complete()`.

- **Redis connection per publish vs. connection pool:** `TracePublisher` opens and closes a Redis connection per `publish()` call. This is deliberate for Celery (fork safety), but means ~5-10ms connection overhead per trace. If throughput becomes a concern, a connection pool scoped to the task would be faster.

- **The SSE terminal detection heuristic is imperfect:** The LLM checks `output_json.action` or `status` for terminal keywords. This works for the current agents but would miss a "done" signal from a future agent that uses different field names. A more robust approach would use a dedicated Redis key (e.g., `order:{id}:done`) set by the Celery task after completion, with the SSE endpoint polling for it.

- **EventSource doesn't support HTTP headers natively:** `streamOrder()` in the frontend uses a plain `new EventSource(url)`, which can't send authentication headers. If auth is added later, the SSE client would need to be replaced with a `fetch`-based reader or an `EventSource` polyfill that supports headers.

- **Unique constraint removal had a ripple effect:** The original `UNIQUE(order_id, step_number)` constraint prevented the orchestrator and executor from having the same step number in their traces. Removing it required no migration changes (the index was non-unique after the fix), but any code relying on `step_number` being unique per order would break silently.
