# Phase 6 — Metrics, Speed Limits, Safety Net, and Startup Order

## The big picture first

Phase 5 finished the features reviewers touch. This one is the
work from the phase reports' own wish lists (phase-4 report, "What's Next"):
the behind-the-scenes gear that keeps the system observable and polite under
pressure. Think dashboard gauges for the whole building, a speed limit on the
front door, a lost-and-found box for jobs that fail for good, and a rule that
the web page waits until the kitchen is actually open.

## What got built

| File | Friendly name | What it does |
|---|---|---|
| `backend/app/api/metrics.py` | The Building Dashboard | One page (`GET /metrics`) with gauges: orders by status, total AI spend, cache hits/misses, job-queue length, lost-and-found size |
| `backend/app/api/rate_limit.py` | The Bouncer's Clicker | Counts each visitor's submissions (30/min); over the limit gets a polite "slow down, retry in N seconds" |
| `backend/app/cache/dlq.py` | The Lost-and-Found Box | Stores permanently failed jobs (order, reason, retry count, timestamp) instead of dropping them |
| `backend/app/tasks/process_order.py` | The Kitchen, with a new rule | When a job fails its last retry, it files the job in the lost-and-found before giving up |
| `backend/app/api/orders.py` | The Reception Desk, stricter | New orders pass the clicker; the order list learned pages (`limit`/`offset`) |
| `backend/app/main.py` | The Front Door Sign | Adds the dashboard to the building directory |
| `backend/tests/test_phase5.py` | The New Exam (11 questions) | Quizzes the dashboard, clicker, lost-and-found, and pages with fakes |
| `docker-compose.yml` | The Opening Checklist | The backend now proves it's awake before the web page starts; health checks on all services |
| `ARCHITECTURE.md` / `DEMO.md` | Map + Tour updates | New endpoints, speed limit, and lost-and-found documented with copy-paste commands |
| `docs /phase5-api-frontend-report.md` + `phase5-docs-audit-report.md` | The Filed Reports | Phase 5 stories live beside the older phase reports |

Left out on purpose: login/auth and multi-tenant (phase-6, a much bigger
project needing your direction) and the Tailwind restyle (would rewrite every
page's look for little reviewer value).

## How each piece works

### The Building Dashboard — `backend/app/api/metrics.py`

Like the gauges in a power plant control room, but as plain text any
monitoring tool can read (Prometheus format). It reports orders per status,
total diary entries, total AI dollars spent, cache hits vs misses, how many
jobs wait in the Celery queue, and how many sit in lost-and-found. The reason
this exists: the phase-4 report explicitly asked for queue-depth and
hit-rate visibility, and reviewers love a single health page. If the database
or Redis is unreachable, every gauge calmly reads 0 instead of crashing the
page — a dashboard that 500s is decoration, not instrumentation.

### The Bouncer's Clicker — `backend/app/api/rate_limit.py`

Think of a bouncer with a clicker: each visitor (IP address) gets 30 tokens
that refill over a minute; each new order costs one. Empty clicker → a tidy
`RATE_LIMITED` (429) envelope with a `retry_after_seconds` hint instead of
silence. If Redis (where clickers live) is down, everyone is waved through —
the reason this exists is that a broken speedometer should never close the
road. This was the phase report's "token bucket per API key" item, keyed by
visitor until login/auth exists to key it properly.

### The Lost-and-Found Box — `backend/app/cache/dlq.py` + kitchen rule

Like a lost-and-found shelf by the exit. Previously, a job that failed all
retries just lay there marked "failed" with its story only in its own diary.
Now the kitchen (`process_order.py`) checks "was that my last allowed retry?"
and, if so, files a card — order id, title, error, retry count, timestamp —
onto the `dlq:orders` shelf in Redis before raising the retry that ends the
run. Filing is best-effort: if Redis is down, the original error still wins
and nothing is masked. Operators list the shelf and the dashboard counts it.

### Pages and startup order — `orders.py`, `docker-compose.yml`

The order list learned book pages: `?limit=10&offset=20` (default book of 50,
never more than 100 per page) so the bulletin board stays fast as history
grows. And the opening checklist finally covers the kitchen: the backend must
pass a health check (it asks itself "are you awake?" via `/api/health`) before
the frontend starts — previously only the database and cache had wake-up
checks, so the web page could open before the kitchen existed.

### The filed reports — phase 5 stories beside the older reports

Phase 5 stories live in `docs /` next to the older phase reports, so
anyone reading the project's history finds the full story in one folder —
one naming scheme (`phaseN-<slug>-report.md`), no duplicates.

## How it all connects

1. Submit → clicker counts you (429 if too fast) → receipt check → kitchen.
2. Kitchen runs agents; traces stream live; costs accumulate.
3. Success → completed; failure → 2 retries → lost-and-found card + failed status.
4. Dashboard (`/metrics`) watches everything: statuses, spend, cache, queues.
5. New exam proves each gear with fakes; map and tour document the new stops.

## Proof it works

Here's what actually happened when we ran it:

- `py_compile` on all new/touched backend files (`metrics.py`,
  `rate_limit.py`, `dlq.py`, `orders.py`, `process_order.py`, `main.py`,
  `test_phase5.py`): clean.
- `docker compose config`: valid — backend health check and frontend's
  wait-for-healthy-backend parsed correctly (needed creating the gitignored
  `.env` from `.env.example`, the normal setup step).
- `grep` sweep: no unprefixed API addresses in the updated docs; all five
  original demo commands plus the three new observability commands verified
  against `main.py`'s router mounts.
- Backend `pytest` (now 14 agent + RAG + 10 integration + 11 phase-5 tests)
  was **not** run here — same standing limitation: no Python installer and
  no Docker daemon on this machine. The command remains
  `docker compose exec backend pytest -v` on a Docker-capable host.

## The one-liner version

| Piece | One-liner |
|---|---|
| `api/metrics.py` | One dashboard page with every gauge that matters, and it never crashes. |
| `api/rate_limit.py` | A 30-per-minute clicker per visitor that says "slow down, retry in N seconds" — and waves everyone through if its own counter is broken. |
| `cache/dlq.py` | A lost-and-found shelf for jobs that fail for good, with order, reason, and timestamp on each card. |
| `tasks/process_order.py` | The kitchen files a lost-and-found card exactly when the last retry fails. |
| `orders.py` | The order list learned book pages; new orders pass the clicker. |
| `docker-compose.yml` | The web page now waits until the backend proves it's awake. |
| `tests/test_phase5.py` | Eleven fake-powered quizzes covering dashboard, clicker, lost-and-found, and pages. |
| Filed phase-5 reports | Both phase 5 stories sit beside the older phase reports. |

## What's next

- [ ] Run `docker compose exec backend pytest -v` on a Docker-capable machine (all suites, no AI key needed)
- [ ] Live pass: `docker compose up`, `curl /metrics`, trip the rate limiter, force a DLQ entry, watch the gauges move
- [ ] Decide: commit strategy for the now-larger changed set (phases 5+6, code, docs)
- [ ] Future, needs direction: API-key auth + multi-tenant (phase 6), Tailwind restyle
