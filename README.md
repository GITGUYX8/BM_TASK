## 1. Framing

You are building a multi-agent pipeline that processes work orders using RAG-augmented LLM reasoning. The pipeline ingests a work order, retrieves relevant context from a vector store, classifies and resolves the order via an agent chain, verifies the result, and streams the decision trace in real-time.

The hard part is depth in the AI core — making agents produce structured, verifiable outputs, designing a RAG pipeline that actually retrieves useful context, managing LLM cost across model tiers, and building observability that lets you debug a multi-turn agent decision. This is what separates an AI Engineer from someone who wires up an API.

AI assistants (Claude, GPT, Copilot, Cursor) are allowed and expected.

## 2. How evaluation works

This is a portfolio project — there is no held-out seed or automated verify gate. Submissions are evaluated on depth in the JD's core competencies:

- **Agent architecture** — typed contracts, state management, verifier-overrules-worker pattern
- **RAG pipeline quality** — chunk strategy, hybrid search, retrieval relevance
- **Prompt engineering** — structured output, few-shot, chain-of-thought where appropriate
- **LLM cost management** — model router with at least 2 tiers, cost ceiling enforcement
- **Observability** — complete agent trace per work order
- **Code quality** — idiomatic stack usage, error handling, testing
- **Integration** — do the agents, RAG, async queue, API, and frontend work together?
- **Documentation + demo** — clear README, architecture decisions documented

## 3. Core architecture mandate

Build exactly what the job description asks for — no more, no less. Every component must exist and work.

### 3.1 Multi-agent pipeline (≥3 agents)

| Agent | Responsibility | Must do |
|---|---|---|
| **Orchestrator** | Receive work order, route to agents, manage state, enforce cost + step budget | Accept `Order` typed input, maintain session state, log cumulative cost, enforce max 8 agent turns |
| **RAG Retriever** | Retrieve relevant context from pgvector | Accept query, perform hybrid search (`<=>` vector + `tsvector` keyword), return top-3 with scores, log retrieval latency |
| **Worker** | Resolve the work order using LLM + RAG context | Output structured resolution using Instructor library or JSON mode, include `confidence: float` and `resolution_summary: str` |
| **Verifier** | Validate worker output against business rules | Accept `Order` + `Resolution`, return `pass/fail/rework` with `reason_code: str` and `explanation: str`. Verifier overrules worker on failure. |

Each agent declares a **typed contract** (Pydantic or Zod) defining its input and output schemas. No agent may produce free-form text output.

### 3.2 RAG pipeline

- **Ingestion:** Chunk strategy (choose: recursive character splitter, semantic chunking, or token-aware splitting). Chunk size between 500–1500 tokens with configurable overlap.
- **Embedding:** Use any embedding model (OpenAI `text-embedding-3-small`, Cohere, or open-source via SentenceTransformers).
- **Hybrid search:** Combine pgvector `<=>` (cosine distance) with PostgreSQL full-text search (`tsvector`/`tsquery`) using weighted fusion.
- **Query rewriting:** Before retrieval, rewrite the user's work order into a search-optimized query (expand abbreviations, extract key entities).
- **Multi-query:** Generate 2–3 query variants, retrieve for each, deduplicate results.
- **Reranking:** Rerank retrieved chunks by relevance before passing to the worker agent.
- Index at least 10 documents for the demo.

### 3.3 Backend API (FastAPI — required per JD)

| Endpoint | Purpose |
|---|---|
| `POST /orders` | Submit a work order → returns `order_id`, enqueues async processing via Celery |
| `GET /orders/:id` | Returns order status + full agent trace (every agent step with input/output/latency/cost) |
| `GET /orders/:id/stream` | SSE endpoint: streams each agent step as it completes |
| `GET /docs` | OpenAPI auto-generated docs |
| `POST /documents` | Ingest a document into the RAG store (title + content + metadata) |

All endpoints return structured errors with machine-readable error codes. Idempotency via `Idempotency-Key` header on `POST /orders`.

### 3.4 Async task queue (Celery — required per JD)

- Each agent step is a separate Celery task in a chain
- Orchestrator enqueues the chain on `POST /orders`
- Failure in any step: retry up to 2 times, then flag the order as `failed` with the error trace

### 3.5 Database

- **PostgreSQL with pgvector** — orders table, agent_traces table, embeddings table (for RAG documents)
- **Redis** — LLM response cache (keyed by normalized prompt, TTL 1 hour), rate limiter state, Celery result backend

### 3.6 Frontend (Next.js App Router — required per JD)

- Submit a work order via a form
- View list of submitted orders with live status (queued → processing → completed/failed)
- SSE-powered real-time trace view: as agents complete, each step appears in an expandable timeline
- Each step shows: agent name, input summary, output, latency, cost, confidence
- State managed via **Zustand** or **Redux** for multi-turn agent state
- Handle error states inline (agent failure, timeout, cost exceeded, API down)

## 4. Observability

Every work order produces an **agent trace** — an append-only log of every agent step:

```
order_id, agent_name, step_number, input_hash, output_summary,
latency_ms, cost_usd, confidence, status (ok/retry/failed/escalated)
```

The trace is queryable via `GET /orders/:id` and displayed in the frontend. A reviewer must be able to reconstruct the full decision path for any order.

## 5. Scale economics

The JD requires "caching strategies for expensive LLM inference calls." Implement:

- **Cost ceiling:** $0.05 per work order. Track cumulative LLM cost. If exceeded, fall back to the cheap model tier for remaining steps.
- **Model router:** At least 2 tiers:
  - Cheap/fast model (e.g., GPT-4o-mini, Claude Haiku, Gemini Flash) — for straightforward classifications and the verifier
  - Capable model (e.g., GPT-4o, Claude Sonnet, Gemini Pro) — for complex reasoning and the worker
- **Redis cache:** Cache LLM responses keyed by (model, prompt_hash, temperature). TTL 1 hour. Log cache hits/misses per order.

## 6. Stack requirements (per JD)

| Layer | Technology | Why |
|---|---|---|
| Frontend | TypeScript, React, Next.js (App Router) | JD explicit requirement |
| State | Zustand or Redux | JD explicit requirement |
| Streaming | Server-Sent Events | JD explicit requirement (SSE/WebSockets) |
| Backend | Python — FastAPI | JD: "undisputed king" |
| Async queue | Celery | JD explicit requirement |
| Database | PostgreSQL + pgvector | JD explicit requirement |
| Cache | Redis | JD explicit requirement |
| LLM | OpenAI / Anthropic / Gemini API | JD explicit requirement |
| Structured output | Instructor library (Python) or Zod (TS) | JD: "JSON mode or Instructor library" |
| Agent framework | LangGraph, CrewAI, AutoGen, or none (raw) | JD explicit topic |
| RAG | Custom pipeline via pgvector | JD explicit requirement |

## 7. Submit list

| Deliverable | What must be in it |
|---|---|
| **Code repository** | Full source. `docker compose up` single-command bootstrap. |
| **README.md** | Architecture overview (1 paragraph), setup instructions, env vars (LLM keys, DB creds), run contract, how to trigger a demo |
| **ARCHITECTURE.md** | Component diagram (ASCII or image), data flow: submit → enqueue → agent chain → RAG → stream → display. Agent contract schemas. Technology choices. |
| **DECISIONS.md** | Key trade-offs: agent framework choice (or why raw), chunk strategy, model selection for each tier, cache invalidation, query rewriting approach, why verifier overrules worker |
| **Tests** | At least one integration test that exercises the full pipeline (submit → agents → RAG → trace). Unit tests for each agent contract. |
| **Demo** | Written walkthrough showing: submitting a work order, agent trace streaming in real-time, expanding a step to see details, an error case (agent failure / budget exceeded), RAG retrieval in action (show source chunks returned) |

## 8. Time model

Self-paced. Recommended: **15–25 hours** for a thorough submission. Focus on depth over breadth — a polished agent core with strong observability scores higher than a sprawling half-working system.

## 9. Tips for a standout submission

- Show **cost-per-order** tracking in the frontend trace view
- Implement **human-in-the-loop**: after 2 verifier rejections, flag the order for manual review
- Handle edge cases: null fields in work orders, LLM API failures with fallback, budget exceeded with graceful degradation
- Log **retrieval relevance** for each RAG call (show which chunks were returned and their scores)
- Use the **Instructor library** for type-safe structured outputs from the LLM
- Add a `POST /orders/:id/retry` endpoint to re-process a failed order
