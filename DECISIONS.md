# Decisions

Key trade-offs for the Work Order Processing System. See `ARCHITECTURE.md` for
the resulting design and `docs/PLAN.md` for the original plan.

| # | Decision | Options considered | Chosen | Rationale |
|---|---|---|---|---|
| 1 | Agent framework | LangGraph, CrewAI, AutoGen, raw loop | Raw loop (`agents/graph.py`, ~70 lines) | 4 nodes + 1 router fit in a `while` loop; zero deps; no LangGraph/Py3.14 compat risk; fully testable without services |
| 2 | Orchestrator intelligence | LLM-based routing vs rule-based | Rule-based `_decide` (priority-ordered if/elif) | Discrete, deterministic action space; LLM would add latency + cost + hallucination risk for no accuracy gain; prompt kept as template for later |
| 3 | Chunk strategy | Recursive character, semantic, token-aware | Recursive character, 1000 tokens / 200 overlap | Inside required 500–1500 range; respects `\n\n,\n,., ,` boundaries; semantic chunking adds complexity without proportional gain on IT docs |
| 4 | Embedding model | OpenAI ada-002, Cohere, SentenceTransformers | `all-MiniLM-L6-v2` (384-dim, local) | Free, no API key, sufficient quality for IT-support domain; pgvector `<=>` cosine |
| 5 | Hybrid search fusion | Vector-only, FTS-only, weighted fusion | Weighted fusion `0.7*vector + 0.3*ts_rank`, top-10 → rerank → top-3 | Vector catches paraphrase, FTS catches error codes/IDs; weights favor semantics while keeping keyword signal |
| 6 | Query rewriting | Rule-based, LLM few-shot, hybrid | LLM few-shot rewrite + 2–3 multi-query variants, dedup by text | Robust to abbreviations/entities in work orders; falls back to no-op rewrite with no API key |
| 7 | Model tiers | Single model, 2 tiers, 3+ tiers | 2 tiers: cheap (verify/classify) vs capable (worker reasoning) | Matches JD; 3+ tiers overcomplicate at this scale; ceiling `$0.05` forces cheap on breach (binary, not gradual — ceiling too small for throttling to matter) |
| 8 | Cache design | TTL-only, LRU, write-through | TTL-only, 1h, key `SHA256(model,prompt,temp)[:16]` | LLM responses idempotent per input; 16-hex truncation readable in Redis CLI, negligible collision risk; Redis outage falls through, never crashes pipeline |
| 9 | Verifier authority | Worker final vs verifier overrules | Verifier overrules worker | Quality gate against hallucination; `fail`→retrieve, `rework`→resolve (max 2), then escalate for human review |
| 10 | Async queue | Celery vs raw asyncio+Redis | Celery chain (single `process_order` task running the graph) | Battle-tested retries, tracking, process isolation; `asyncio.run` wrapper because Celery async tasks still experimental; one container added via compose |
| 11 | Streaming | SSE vs WebSockets vs polling | SSE (`text/event-stream`, named `step/complete/error` events) | Unidirectional server→client; native EventSource, zero deps, auto-reconnect; `GET`-then-SSE pattern handles already-complete orders |
| 12 | Frontend state | Zustand vs Redux vs Context | Zustand | Minimal boilerplate for orders + live traces; dedup-by-(step,agent) guard against redelivery |
| 13 | Idempotency semantics | Ignore key, key→same order, key+body check | Key lookup; same body → 200 replay, different body → 409 `IDEMPOTENCY_MISMATCH` | Prevents duplicate Celery work on client retries without masking real conflicts |
| 14 | SSE/insert ordering | Publish-then-persist vs persist-then-publish | Publish per step via `on_trace`, persist at task end | UI streams live before DB commit; terminal `GET` refetch reconciles |
| 15 | Cost precision | float vs Decimal | `Decimal` everywhere (NUMERIC(8,6)) | Avoids float drift against the `$0.05` ceiling |

## Gotchas learned

- `asyncio.run()` inside Celery works on the default prefork pool; it breaks on
  gevent pools (use a dedicated loop there).
- `TracePublisher` opens/closes Redis per publish — fork-safe for Celery at the
  cost of ~5–10ms per trace; pool per task if throughput matters.
- `(order_id, step_number)` must NOT be unique — orchestrator and executor share
  step numbers; index is non-unique (`db/models.py`).
- `EventSource` cannot send auth headers — SSE stays unauthenticated or moves to
  `fetch`-reader when auth lands.
