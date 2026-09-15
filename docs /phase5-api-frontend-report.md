# Phase 5 — Idempotent Orders, Retry, Live Frontend, and Guidebooks

## The big picture first

Our work-order system could already take a job, think it through with AI
agents, and show the thinking live. But it was missing the boring grown-up
stuff: what happens if your browser sends the same request twice, how do you
redo a failed job, and where is any of this written down? This phase
adds all of that — safety receipts, a redo button, a clearer live feed, a
nicer status page, and three guidebooks at the front door.

## What got built

| File | Friendly name | What it does |
|---|---|---|
| `backend/app/api/orders.py` | The Reception Desk | Hands out safety receipts, allows redos, and narrates live progress |
| `backend/tests/test_integration.py` | The Examiner | Ten tests that quiz the reception desk without needing live services |
| `frontend/lib/api.ts` | The Phone Line | Talks to the backend and translates error messages into plain codes |
| `frontend/app/orders/[id]/page.tsx` | The Status Board | The live order page with cost bar, badges, and a retry button |
| `frontend/components/CostBar.tsx` | The Fuel Gauge | Shows AI spending vs the $0.05 budget, turns red when over |
| `frontend/components/RetrievedChunks.tsx` | The Receipt Drawer | Shows which knowledge-base passages the AI actually read, with scores |
| `frontend/components/StatusBadge.tsx` | The Name Tag | A colored pill: grey queued, blue working, green done, red failed |
| `frontend/components/TraceTimeline.tsx` | The Diary | The expandable step-by-step log of what each agent did |
| `frontend/components/OrderList.tsx` | The Bulletin Board | The list of all orders, now with name tags and honest error messages |
| `frontend/components/OrderForm.tsx` | The Front Counter | The submit form, now shows error codes like `ORDER_NOT_FOUND` |
| `frontend/lib/store.ts` | The Short-Term Memory | Remembers orders and live updates, ignores duplicate deliveries |
| `ARCHITECTURE.md` | The Building Map | Diagram, data flow, agent contracts, database layout |
| `DECISIONS.md` | The Diary of Choices | Fifteen "we picked X because..." trade-offs |
| `DEMO.md` | The Guided Tour | Copy-paste walkthrough: submit, watch, inspect, break, retry |

## How each piece works

### The Reception Desk — `backend/app/api/orders.py`

Think of it as a hotel front desk that finally learned manners. When you
submit an order you may include a safety receipt (`Idempotency-Key`, a random
ID your browser makes up). Same receipt + same request → the desk smiles and
returns your existing order instead of booking you twice. Same receipt but a
*different* request → it stops you with a `IDEMPOTENCY_MISMATCH` warning,
because something got mixed up. It also learned a redo: `POST
/orders/:id/retry` wipes a failed order's diary clean, resets its spending to
zero, and sends it back through the kitchen — but only if it actually failed.
Trying to redo a job that's still cooking gets a polite `ORDER_PROCESSING`
refusal. And every error now arrives in a tidy envelope
(`{ error: { code, message, details } }`) instead of a mumbled apology.

### The Examiner — `backend/tests/test_integration.py`

Like an exam with ten questions, all answerable without calling the real AI
or database. It feeds the system fake orders and a fake database, then checks:
does the full agent chain produce a diary with real entries? Does a repeated
receipt return the same order? Does a mismatched receipt get rejected? Does a
missing order report `ORDER_NOT_FOUND`? Does retry reset and requeue, and does
retrying a healthy order get refused? The reason this exists is simple: the
old file just said `assert True`, which is an exam where everyone passes by
showing up.

### The Phone Line — `frontend/lib/api.ts`

Think of it as the translator between the web page and the backend. It now
makes up a safety receipt for every new order automatically, understands the
new error envelopes (turning them into typed `ApiError`s with codes you can
actually read), and learned two new phrases: "list only the escalated ones"
and "please retry this order".

### The Status Board — `frontend/app/orders/[id]/page.tsx`

Like a parcel-tracking page, but for AI thinking. It first loads everything
already known, then opens a live stream for updates as each agent finishes.
It now listens for three named announcements — `step` (one more diary entry),
`complete` (all done), `error` (something failed) — while still understanding
the old unnamed chatter for backward compatibility. When the end arrives, it
re-reads the full order so the numbers match. Failed jobs get a Retry button.

### The Fuel Gauge — `frontend/components/CostBar.tsx`

Like the fuel gauge in a car, but for AI money. It shows `$spent / $0.05` with
a bar that slides green → yellow → red. Past 100% it adds a plain-English
note: the budget is blown, so the remaining steps use the cheap AI model.
This matters because every order has a hard spending cap.

### The Receipt Drawer — `frontend/components/RetrievedChunks.tsx`

Like asking "show me your sources" and actually getting them. Inside the
retriever's diary entry, a "Show source chunks" drawer lists the 3 passages
the AI read, each with its relevance score and a short preview. This is the
proof the RAG pipeline (the system's library lookup) really did its job.

### The Name Tag, Diary, Bulletin Board, Front Counter, Memory — small pieces

The Name Tag (`StatusBadge`) colors each status so you can scan a list at a
glance. The Diary (`TraceTimeline`) now flags cached answers and opens the
Receipt Drawer. The Bulletin Board (`OrderList`) can filter (e.g. only
escalated) and admits failure honestly instead of going blank. The Front
Counter (`OrderForm`) repeats error codes instead of `[object Object]`. The
Short-Term Memory (`store.ts`) finally knows what a trace looks like
(previously just `unknown`) and refuses to paste the same diary entry twice —
live streams sometimes repeat themselves.

### The three guidebooks — `ARCHITECTURE.md`, `DECISIONS.md`, `DEMO.md`

The Building Map draws the whole system on one page: who talks to whom, what
each AI agent promises to deliver, how the database is laid out, and how live
updates travel. The Diary of Choices records fifteen forks in the road
("why no LangGraph?", "why two AI tiers?", "why SSE instead of WebSockets?")
with the reasoning, so future-you doesn't have to guess. The Guided Tour is a
copy-paste script: submit an order, watch it stream, inspect the sources,
break something, retry it, run the tests.

## How it all connects

1. You submit at the Front Counter → the Phone Line attaches a safety receipt.
2. The Reception Desk checks the receipt, books the order, and sends it to the AI kitchen (Celery worker).
3. Each agent writes a diary entry → broadcast live (`step` events) and saved to the database.
4. The Status Board collects entries live; the Fuel Gauge fills; the Receipt Drawer shows sources.
5. Done → `complete`; failed → `error` + Retry button → Reception Desk wipes and requeues.
6. The Examiner replays all of this with fakes so regressions get caught.
7. The guidebooks explain the building to the next visitor.

## Proof it works

Here's what actually happened when we ran things:

- `tsc --noEmit` on the frontend: exit 0, zero type errors.
- `npm run build` (production): compiled successfully, all 4 routes generated (`/`, `/orders`, `/orders/[id]`, not-found).
- `py_compile` on the backend files and new tests: clean.
- Backend `pytest` was **not** run here — this machine has no Python package
  installer and the Docker service is unreachable (permission denied on its
  socket). The new tests are mock-based and need no AI key, so the next step
  is `docker compose exec backend pytest -v` on a machine where Docker works.
  That's the honest gap; everything else above is observed, not assumed.

## The one-liner version

| Piece | One-liner |
|---|---|
| `backend/app/api/orders.py` | The desk now takes safety receipts, offers redos, speaks in clear error codes, and narrates live progress by name. |
| `backend/tests/test_integration.py` | Ten fake-database quizzes prove receipts, redos, errors, and the full agent diary behave. |
| `frontend/lib/api.ts` | The translator auto-attaches receipts, reads error codes, and learned "retry" and "filter". |
| `frontend/app/orders/[id]/page.tsx` | The tracking page shows cost, status colors, sources, and a retry button while listening to the new live announcements. |
| `frontend/components/CostBar.tsx` | A fuel gauge for AI spending that turns red and explains the cheap-model fallback. |
| `frontend/components/RetrievedChunks.tsx` | A "show your sources" drawer with scores and previews inside the retriever's diary entry. |
| `frontend/lib/store.ts` | Memory that knows what a trace is and never pastes the same entry twice. |
| `ARCHITECTURE.md` | One-page map of the whole building: diagram, flow, contracts, database, costs, errors. |
| `DECISIONS.md` | Fifteen "we chose X because..." stories so nobody has to re-argue them. |
| `DEMO.md` | A copy-paste tour: submit, watch, inspect sources, break, retry, test. |

## What's next

- [ ] Run `docker compose exec backend pytest -v` where Docker works (14 agent + RAG + 10 new integration tests, no AI key needed)
- [ ] Live demo pass: `docker compose up --build`, seed data, submit the sector-7G order, watch `step/complete` events via `curl -N .../stream` and the UI
- [ ] Decide: one commit or split per workstream (6 workstreams touched these files)
- [ ] Possible follow-up: rate limiting / auth, deliberately left out of this phase
