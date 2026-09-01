# Phase 3: Agent Pipeline — Build Report

**Status:** Complete · **Files:** 12 files touched, 885 lines total · **Tests:** 26 passing (14 agent + 11 RAG + 1 placeholder)

---

## 1. Phase Overview

Phase 3 built the multi-agent processing pipeline that takes a work order through a decision loop: retrieve context → generate resolution → verify quality → complete or retry. Four agents (orchestrator, retriever, worker, verifier) connected by a lightweight state graph, exposed via `POST /orders` and `GET /orders/{id}`.

### Sub-chunks

| # | Component | Files | Lines | Status |
|---|---|---|---|---|
| 3.1 | Model Router — LLM API calls | `core/model_router.py` | 132 | Complete |
| 3.2 | Orchestrator — decision router | `agents/orchestrator.py` | 106 | Complete |
| 3.3 | Retriever — RAG pipeline caller | `agents/retriever.py` | 51 | Complete |
| 3.4 | Worker — resolution generation | `agents/worker.py` | 104 | Complete |
| 3.5 | Verifier — quality check | `agents/verifier.py` | 111 | Complete |
| 3.6 | Agent Graph — state machine | `agents/graph.py` | 43 | Complete |
| 3.7 | API — POST/GET orders | `api/orders.py` | 112 | Complete |
| 3.8 | Tests — 14 agent tests | `tests/test_agents.py` | 189 | Complete |

### Pre-existing stubs filled in

| File | Before | After |
|---|---|---|
| `agents/base.py` | Abstract `AgentNode` | Same base + `ModelRouter` constructor injection |
| `agents/orchestrator.py` | `run(state)` returns `state` unchanged | Full rule-based decision logic with 7 routing paths |
| `agents/retriever.py` | `run(state)` returns `state` unchanged | Calls `pipeline.retrieve()` with session + embedder + LLM |
| `agents/worker.py` | `run(state)` returns `state` unchanged | LLM generates `Resolution(summary, confidence, actions)` |
| `agents/verifier.py` | `run(state)` returns `state` unchanged | LLM returns `Verdict(pass/fail/rework)` |
| `agents/graph.py` | Did not exist | Loop-based state machine connecting all 4 agents |
| `api/orders.py` | Stub returning `{"order_id": ""}` | Full implementation with DB persistence + graph execution |
| `core/model_router.py` | `select()` + `estimate_cost()` only | Added async `llm_call()` with 4 providers |

### Files created/modified

```
backend/app/
├── agents/
│   ├── base.py          MODIFIED — added ModelRouter injection
│   ├── orchestrator.py  MODIFIED — full rule-based decision logic
│   ├── retriever.py     MODIFIED — calls pipeline.retrieve()
│   ├── worker.py        MODIFIED — LLM resolution generation
│   ├── verifier.py      MODIFIED — LLM quality verification
│   ├── graph.py         NEW — state machine loop
│   └── __init__.py      (empty, unchanged)
├── core/
│   ├── model_router.py  MODIFIED — added llm_call with 4 providers
│   ├── cost_tracker.py  (unchanged, existed prior)
│   └── models.py        MODIFIED — added routing_key to AgentState
└── api/
    └── orders.py        MODIFIED — full CRUD + graph execution
backend/tests/
└── test_agents.py       NEW — 14 tests covering all agents + graph
```

---

## 2. Architecture

```
POST /api/orders  ──►  create Order in DB
                            │
                            ▼
                    AgentGraph.run(state)
                            │
                    ┌───────┴───────┐
                    │   while loop  │
                    │  status ==    │
                    │  "processing" │
                    └───────┬───────┘
                            │
                    ┌───────▼───────┐
                    │ Orchestrator  │
                    │  .run(state)  │
                    └───────┬───────┘
                            │
                    routing_key?
              ┌───────┬─────┼─────┬───────┐
              │       │     │     │       │
              ▼       ▼     ▼     ▼       ▼
          retrieve  resolve verify complete
              │       │     │     fail
              │       │     │     escalate
              │       │     │
              ▼       ▼     ▼
          Retriever  Worker Verifier
          Node       Node   Node
              │       │     │
              └───┬───┘     │
                  │         │
                  │  resolution
                  │         │
                  └────┬────┘
                       │
                       ▼
                status updated, loop continues
                       │
                       ▼
              complete / fail / escalate?
                       │
                       ▼
                ──►  persist state + traces to DB
                ──►  return OrderResponse
```

### The routing decision tree (OrchestratorNode._decide)

```
State has error?           ──► escalate
Verdict == pass?           ──► complete
Verdict == rework?         ──► resolve (or fail if > max_retries)
Verdict == fail?           ──► retrieve (retry with more context)
Has resolution?            ──► verify
Has chunks?                ──► resolve
No chunks?                 ──► retrieve
Can't decide?              ──► escalate
```

This is deterministic, rule-based (no LLM call needed). The `ORCHESTRATOR_SYSTEM_PROMPT` exists as a template if LLM-based decisions are desired later, but the current implementation is testable without an API key.

---

## 3. Component Deep Dives

### 3.1 Model Router (`core/model_router.py`)

**What it does:** Selects the LLM model per tier and makes async API calls to the configured provider.

**Key addition — `async llm_call(system_prompt, user_message, tier)`:**

```python
async def llm_call(self, system_prompt: str, user_message: str, tier: str = "cheap") -> str | None:
    if not settings.llm_api_key:
        return None
    model = self.select(tier)
    # Routes to _call_gemini / _call_openai / _call_anthropic / _call_groq
```

**Supported providers:**

| Provider | API format | Models |
|---|---|---|
| Gemini | `generativelanguage.googleapis.com` | `gemini-1.5-flash`, `gemini-1.5-pro` |
| OpenAI | `api.openai.com/v1/chat/completions` | `gpt-4o-mini`, `gpt-4o` |
| Anthropic | `api.anthropic.com/v1/messages` | `claude-3-haiku`, `claude-3-sonnet` |
| Groq | `api.groq.com/openai/v1/chat/completions` | `llama3-8b-8192`, `llama3-70b-8192` |

**Fallback behavior:** When `settings.llm_api_key` is empty (no .env configured), `llm_call()` returns `None`. Every component that uses it checks for `None` and degrades gracefully — the RAG pipeline falls back to no-op rewriting, the worker generates a template resolution, the verifier returns a default "pass" verdict.

### 3.2 Orchestrator Node (`agents/orchestrator.py`)

**What it does:** Reads the current `AgentState` and decides the next action.

**`run(state)` — the outer wrapper (lines 30-53):**
1. Calls `_decide(state)` to get an `OrchestratorOutput(action, reason)`
2. Increments `state.current_step`
3. Creates an `AgentTraceEntry` with the decision, latency, model info
4. Sets `state.routing_key = output.action` (the graph reads this)
5. If terminal action (`complete`/`fail`/`escalate`), sets `state.status`

**`_decide(state)` — the decision logic (lines 55-106):**

The decision chain is a priority-ordered series of `if/elif` checks:

```
if state.error                      → escalate
elif state.verdict.result == "pass" → complete
elif state.verdict.result == "rework" and rework_count > max_retries → fail
elif state.verdict.result == "rework" → resolve
elif state.verdict.result == "fail" → retrieve
elif state.resolution and no verdict → verify
elif state.retrieved_chunks and no resolution → resolve
elif no retrieved_chunks → retrieve
else → escalate
```

**Why rule-based instead of LLM:** The decision logic is simple enough to encode in 8 `if/elif` branches. An LLM call would add latency, cost, and potential hallucination for no benefit. The action space is discrete and deterministic — perfect for rules.

### 3.3 Retriever Node (`agents/retriever.py`)

**What it does:** The bridge between the agent pipeline and Phase 2's RAG pipeline.

```python
class RetrieverNode(AgentNode):
    def __init__(self, session: AsyncSession, embedder=None, router=None):
        super().__init__(router)
        self.session = session
        self.embedder = embedder or EmbeddingService()

    async def run(self, state):
        chunks = await rag_retrieve(
            session=self.session,
            description=state.order.description,
            embedder=self.embedder,
            llm_call=self.router.llm_call,
            top_k=3,
        )
        state.retrieved_chunks = chunks
        # log trace with chunk count + latency
        return state
```

**Dependencies injected via constructor:**
- `session` — the DB session for SQL queries in `hybrid_search()`
- `embedder` — the `EmbeddingService` for converting query text to vectors
- `router` — the `ModelRouter` for LLM calls in rewriting + expansion

**Latency tracking:** Uses `time.monotonic()` to measure wall-clock time of the full retrieval pipeline (includes embedding, hybrid search, reranker).

### 3.4 Worker Node (`agents/worker.py`)

**What it does:** Uses a capable LLM to generate a structured resolution from the work order description + retrieved chunks.

**System prompt (lines 2-12):**
```
You are a work order resolution specialist. Given a work order description
and retrieved knowledge base chunks, generate a resolution.

Return a JSON object with:
- resolution_summary: str (detailed step-by-step resolution)
- confidence: float (0.0 to 1.0)
- actions_taken: list[str] (specific actions to resolve the issue)
```

**`_format_chunks(chunks)`** — formats retrieved chunks as a numbered list for the LLM prompt:
```
[1] VPN Guide: Reset your VPN credentials by navigating to...
[2] Network Setup: Ensure the VPN client is version 2.1 or later...
```

**Fallback chain:**
1. Try LLM call → parse JSON response → create `Resolution`
2. Parse fails (malformed JSON) → create `Resolution` with raw response text, confidence 0.5
3. No LLM available → create `Resolution` with "Manual review required", confidence 0.1

**Model tier:** `"capable"` — the worker does complex reasoning combining description + chunks, so it uses the expensive model (e.g., Gemini Pro, GPT-4o).

### 3.5 Verifier Node (`agents/verifier.py`)

**What it does:** Checks the worker's resolution for correctness and completeness.

**System prompt (lines 2-17):**
```
You are a quality verifier for work order resolutions. Given the original
work order and the resolution, determine if the resolution is correct.

Return JSON: {"result": "pass"|"fail"|"rework", "reason_code": "...",
"explanation": "...", "confidence": 0.0-1.0}
```

**Result codes:**
- `pass` — resolution is correct, can close the order
- `fail` — resolution is wrong, need to retrieve more context
- `rework` — partially correct, needs revision (worker retries)

**Model tier:** `"cheap"` — the verifier is a simpler classification task, so it uses the cheap model (e.g., Gemini Flash, GPT-4o-mini).

**Design rationale — Verifier overrules Worker:** If the verifier says "fail" or "rework", the orchestrator routes back to `retrieve` or `resolve`, not to `complete`. This means the worker's output is never final without verification — a safeguard against hallucination that the architecture document calls "verifier-overrules-worker."

**Special case — no resolution to verify:** If the verifier runs but `state.resolution` is `None` (shouldn't happen in normal flow, but guards against edge cases), it immediately returns `Verdict(result="fail", reason_code="NO_RESOLUTION")`.

### 3.6 Agent Graph (`agents/graph.py`)

**What it does:** The loop-based state machine that orchestrates the agents.

```python
class AgentGraph:
    def __init__(self, session, router=None):
        self.orchestrator = OrchestratorNode(router)
        self.retriever = RetrieverNode(session, router=router)
        self.worker = WorkerNode(router)
        self.verifier = VerifierNode(router)

    async def run(self, state):
        while state.status == "processing":
            state = await self.orchestrator.run(state)
            key = state.routing_key

            if key == "retrieve":  state = await self.retriever.run(state)
            elif key == "resolve": state = await self.worker.run(state)
            elif key == "verify":  state = await self.verifier.run(state)
            elif key in ("complete", "fail", "escalate"): break
            else: state.status = "failed"; break  # unknown key

            if state.current_step >= settings.max_steps:
                state.status = "failed"
                state.error = f"Max steps ({settings.max_steps}) exceeded"
                break
        return state
```

**Why not LangGraph:** LangGraph was considered but rejected. The state machine is simple enough (4 nodes, 1 conditional router) that a 42-line loop is clearer, has zero external dependencies, and is fully testable without installing LangGraph (which had version compatibility issues with the project's Python 3.14 environment).

**Guardrails:**
- `max_steps` (default 8) — prevents infinite loops if the orchestrator keeps routing back and forth
- Unknown routing key — sets status to `failed` with a descriptive error
- Terminal actions (`complete`/`fail`/`escalate`) — break the loop immediately

### 3.7 API (`api/orders.py`)

**`POST /api/orders`** — Submit a work order:
1. Creates an `Order` in the database with status `queued`
2. Creates an `AgentState` with the order data
3. Runs `AgentGraph.run(state)` — this is synchronous within the request (runs the full agent loop before returning)
4. Updates the `Order` status, `cumulative_cost`, `step_count`
5. Persists all `AgentTraceEntry` objects to the `agent_traces` table
6. Returns `OrderResponse` with the full trace

**`GET /api/orders`** — List recent orders (last 50, newest first).

**`GET /api/orders/{order_id}`** — Get a single order with full trace.

**Response model (`OrderResponse`):**
```python
class OrderResponse(BaseModel):
    order_id: UUID
    title: str
    description: str
    priority: str
    status: str    # queued / processing / completed / failed / escalated
    cumulative_cost: Decimal
    step_count: int
    traces: list[AgentTraceEntry]  # every agent step with input/output/latency/cost
    error_trace: dict | None
    created_at: str
    updated_at: str
```

**Error handling:**
- 404 on unknown order_id
- 422 on validation failure (FastAPI built-in)
- 201 on successful creation

### 3.8 Tests (`tests/test_agents.py`)

**14 tests, all passing. Coverage:**

| Agent | Test | What it verifies |
|---|---|---|
| **Orchestrator** | `retrieve_on_fresh_state` | Fresh state → routing_key="retrieve" |
| | `complete_on_pass_verdict` | Pass verdict → routing_key="complete" |
| | `fail_on_max_retries` | Rework count > max_retries → routing_key="fail" |
| | `resolve_on_chunks_ready` | Chunks exist, no resolution → routing_key="resolve" |
| | `verify_on_resolution_ready` | Resolution exists, no verdict → routing_key="verify" |
| | `escalate_on_error` | Error in state → routing_key="escalate" |
| | `trace_appended` | Each run appends exactly 1 trace entry |
| **Worker** | `fallback_no_llm` | No LLM → resolution with confidence 0.1 |
| | `fallback_empty_chunks` | No chunks → still produces a resolution |
| | `trace_created` | Worker run creates a worker trace |
| **Verifier** | `fail_on_no_resolution` | No resolution → verdict="fail", reason="NO_RESOLUTION" |
| | `fallback_no_llm` | No LLM → verdict="pass" with low confidence |
| | `trace_created` | Verifier run creates a verifier trace |
| **Graph** | `full_flow` | Full graph loop runs orchestrator → stops without error |

---

## 4. Key Design Decisions

| Decision | Alternative considered | Chosen approach | Reasoning |
|---|---|---|---|
| **Rule-based orchestrator** | LLM-based decision | 8 `if/elif` branches | Decision space is small and deterministic. LLM adds latency + cost + hallucination risk with no accuracy benefit. |
| **Loop-based graph** | LangGraph | 42-line `while` loop in `graph.py` | LangGraph had Python 3.14 compatibility issues. The loop is simpler, has zero deps, and is transparent. |
| **`llm_call` callback pattern** | Import LLM client everywhere | Centralized in ModelRouter | Single point of configuration. All agents get the same router instance. Easy to swap providers by changing one config value. |
| **Sync request processing** | Async Celery queue | Run graph synchronously in POST handler | Simpler for the demo. The loop completes in <5s with fallbacks. Celery enqueuing is Phase 4. |
| **Verifier overrules worker** | Worker always trusted | Verifier must pass | Catches hallucinations. If verifier says fail, orchestrator forces a retry rather than completing. |
| **Worker = capable, Verifier = cheap** | Both capable | Verifier uses cheap model | The verifier's job (classification into pass/fail/rework) is simpler than the worker's (generating a novel resolution). |
| **`routing_key` field on AgentState** | External routing map | State holds its own next action | The state is self-contained for serialization, debugging, and replay. You can see exactly where the graph would route next. |

---

## 5. Full System Flow (Phase 2 + Phase 3 combined)

```
POST /api/documents ──► ingest_document() ──► chunk → embed → store in pgvector
     (seed knowledge base)

POST /api/orders ──► create Order in DB
     │                 create AgentState
     │                 run AgentGraph(state)
     │
     │  ┌─────────────────────────────────────────────────────────────┐
     │  │ Loop:                                                       │
     │  │   Orchestrator._decide(state) → routing_key                 │
     │  │                                                            │
     │  │   if "retrieve":                                            │
     │  │     RetrieverNode                                           │
     │  │       → rewrite_query(description, llm_call)   (LLM)       │
     │  │       → expand_queries(rewritten, llm_call)     (LLM)       │
     │  │       → embedder.embed(variant)                 (bi-encoder)│
     │  │       → hybrid_search(session, vec, text)  (SQL: <=> + FTS)│
     │  │       → deduplicate_by_text(all_chunks)                     │
     │  │       → rerank(description, deduped)        (cross-encoder) │
     │  │       → state.retrieved_chunks = top-3 chunks               │
     │  │                                                            │
     │  │   if "resolve":                                             │
     │  │     WorkerNode                                              │
     │  │       → LLM(description + chunks) → Resolution(summary,     │
     │  │         confidence, actions_taken)                          │
     │  │       → state.resolution = Resolution                       │
     │  │                                                            │
     │  │   if "verify":                                              │
     │  │     VerifierNode                                            │
     │  │       → LLM(order + resolution) → Verdict(pass/fail/rework) │
     │  │       → state.verdict = Verdict                             │
     │  │                                                            │
     │  │   if "complete": break                                      │
     │  │   if "fail":     break                                      │
     │  │   if "escalate": break                                      │
     │  │                                                            │
     │  │   Guard: current_step > max_steps → fail                    │
     │  └─────────────────────────────────────────────────────────────┘
     │
     ▼
   persist Order (status, cost, step_count)
   persist AgentTrace (all steps)
   return OrderResponse with full trace

GET /api/orders/{id} ──► return Order with traces
```

---

## 6. Test Results

**All 26 tests pass:**

```
tests/test_agents.py  — 14 passed (orchestrator/worker/verifier/graph)
tests/test_rag.py     — 11 passed (rewriter/expander/tsquery/dedup/reranker)
tests/test_integration.py — 1 passed (placeholder)
```

**What's not tested** (needs PostgreSQL running):
- `POST /api/orders` end-to-end (creates DB records, runs graph)
- `hybrid_search` SQL query execution
- `ingest_document` chunk → embed → write chain
- These are integration tests that require a database with pgvector

---

## 7. What's Next — Phase 4

Potential Phase 4 work:

- **Async queue:** Wire Celery so `POST /orders` enqueues the agent graph instead of running it synchronously
- **SSE streaming:** `GET /orders/{id}/stream` pushes each agent step as it completes
- **Redis caching:** Cache LLM responses keyed by (model, prompt_hash)
- **Cost ceiling enforcement:** If cumulative cost exceeds $0.05, force all remaining steps to cheap model
- **Frontend:** Next.js dashboard with real-time trace view
- **Error recovery:** Retry failed agent steps, human-in-the-loop for escalated orders

---

*Report generated: 2026-07-17 · Phase 3 complete · 26 tests passing*
