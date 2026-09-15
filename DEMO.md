# Demo walkthrough

## Prerequisites

```bash
cp .env.example .env        # set LLM_PROVIDER + LLM_API_KEY (optional; offline fallbacks work)
docker compose up --build
docker compose exec backend python -m scripts.seed_documents --count 12
```

Frontend: http://localhost:3000 · API docs: http://localhost:8000/docs

## 1. Submit a work order

```bash
curl -X POST http://localhost:8000/api/orders \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-001" \
  -d '{"title": "Network outage in sector 7G",
       "description": "Users in building 7G report intermittent connectivity since 14:00 UTC. Affects ~200 workstations on VLAN 42.",
       "priority": "high"}'
# → 201 { "order_id": "<uuid>", "status": "queued", ... }
```

Re-posting with the same `Idempotency-Key` and body returns `200` with the same
`order_id` (no duplicate Celery job). A different body with the same key returns
`409 { "error": { "code": "IDEMPOTENCY_MISMATCH", ... } }`.

Or use the web UI at `/` (title + description + priority → Submit).

## 2. Watch the agent trace stream in real time

```bash
curl -N http://localhost:8000/api/orders/<order_id>/stream
# event: step
# data: {"agent_name":"orchestrator","step_number":1,...}
# event: step
# data: {"agent_name":"retriever",...,"output_json":{"chunks":[...]}}
# event: step
# data: {"agent_name":"worker",...,"confidence":0.9,...}
# event: step
# data: {"agent_name":"verifier",...,"output_json":{"result":"pass",...}}
# event: complete
# data: {"order_id":"<uuid>","status":"completed"}
```

In the UI, open `/orders/<uuid>`: header shows `StatusBadge`, `CostBar`
(`$cost / $0.05` with green→yellow→red), step count; each timeline entry expands
to input/output summaries, latency, model, cost, cache-hit flag.

## 3. Expand a step — RAG retrieval in action

Expand the `retriever` step → "Show source chunks (3)": each chunk lists
`document_title`, `fused_score` (plus vector/keyword components) and a 300-char
snippet. Compare with the raw endpoint:

```bash
curl http://localhost:8000/api/orders/<order_id> | python -m json.tool
# traces[].output_json.chunks[] → document_title, fused_score, vector_score, keyword_score
```

## 4. Error case — failure and retry

Failed/escalated orders surface inline: red `error_trace` block on the detail
page plus `event: error` on the stream. List the human-review queue:

```bash
curl "http://localhost:8000/api/orders?status=escalated"
```

Re-process from scratch (clears traces, resets cost/steps, requeues Celery):

```bash
curl -X POST http://localhost:8000/api/orders/<order_id>/retry
# → 202 with status "queued"; only failed/escalated orders accepted,
#   otherwise 409 { "error": { "code": "ORDER_PROCESSING", ... } }
```

The UI shows a "Retry order" button under the same conditions.

## 5. Budget-exceeded degradation

Submit several orders (or set `COST_CEILING=0.00` in `.env` and restart) so the
tracker trips: `CostBar` hits 100% red with "remaining steps use cheap model
tier", and worker/verifier traces report the cheap model. No crash — graceful
degradation by design.

## 6. Run the tests

```bash
docker compose exec backend pytest -v
# test_agents.py (14) + test_rag.py + test_integration.py (idempotency,
# structured errors, retry, full graph trace) — no LLM key required.
```
