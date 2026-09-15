# Phase 5 — Docs Audit and Fixes

## The big picture first

Fresh docs are only useful if you can trust them. This report is a
proofreading pass over the three guidebooks from the phase 5 frontend
report (`ARCHITECTURE.md`, `DECISIONS.md`, `DEMO.md`): every command and every
technical claim was checked against the real code. Two copy-paste commands
that would have failed were caught and fixed, plus two small wording
cleanups. Think of it as tasting every dish before the menu goes to print.

## What got built

| File | Friendly name | What it does |
|---|---|---|
| `DEMO.md` (fixed) | The Guided Tour, corrected | All five demo commands now point at the right address; seed command points at the real script |
| `ARCHITECTURE.md` (fixed) | The Building Map, corrected | Status codes stated precisely; every endpoint shows its true `/api` address |
| This report (`phase5-docs-audit-report.md`) | This story | Plain-English record of what was checked, what broke, and what was fixed |

`DECISIONS.md` needed no changes — every claim in it checked out.

## How each piece works

### The wrong addresses — `DEMO.md` curl fixes

Think of it like printing invitations with the street name but no house
number. The backend serves everything under an `/api` hallway (`main.py`
mounts both routers with `prefix="/api"`), but the tour's five example
commands knocked on the bare door (`http://localhost:8000/orders`), which
would have answered 404. All five now knock correctly
(`http://localhost:8000/api/orders`, `.../stream`, `.../retry`,
`...?status=escalated`). The API-docs link (`/docs`) was left alone — that
one genuinely lives outside the hallway, so it was already right.

### The seed mix-up — `DEMO.md` seed fix

Like telling someone to start the car with the house key. The tour said
`python -m app.rag.seed_data`, but that file is just a pantry — a list of
demo documents with no runnable part. The real starter is
`scripts/seed_documents.py` (it reads the pantry and loads each document
into the database). The tour now says
`docker compose exec backend python -m scripts.seed_documents --count 12`,
copied from that script's own instructions.

### The vague numbers — `ARCHITECTURE.md` fixes

The map said submitting an order returns "202/201", which is hedging. The
code is exact: `201` for a brand-new order, `200` when your safety receipt
replays an existing one, `202` for a retry. It says that now. The diagram and
flow list also show the full `/api/...` addresses with a note that all
routes live under the `/api` prefix.

### The clean bills of health

The audit checked the nerdy details too, and they all matched the code:
chunk size 1000 with 200 overlap (`rag/chunker.py`), search blend 0.7/0.3
(`rag/retriever.py`), top-10 search narrowed to top-3 (`rag/pipeline.py`),
cache fingerprint truncated to 16 characters with a 1-hour expiry
(`cache/redis.py`), the agent loop exactly 70 lines (`agents/graph.py`),
2 retries on failure, 14 agent tests, and every error code in the catalog.
The reason this exists: docs rot the moment nobody checks them, and a demo
that 404s on step one is worse than no demo.

## How it all connects

1. Audit read all three guidebooks cover to cover.
2. Each command and claim was traced to its source file (`main.py`,
   `orders.py`, `seed_documents.py`, `chunker.py`, `retriever.py`,
   `pipeline.py`, `redis.py`, `graph.py`).
3. Two bugs + two wording issues found, all four fixed.
4. A sweep confirmed no unprefixed API addresses remain.
5. Branch survey confirmed no competing phase docs anywhere, so the
   fixes are the single source of truth.
6. This story recorded the whole pass.

## Proof it works

Here's what actually happened when we ran it:

- `grep` for bare `localhost:8000/orders` across `DEMO.md` and
  `ARCHITECTURE.md`: zero hits left (the only `/docs` hit is the correct
  docs address).
- `grep` confirms all five demo commands use `/api/...` and the seed line
  uses `scripts.seed_documents`.
- `grep` confirms the precise status-code wording in `ARCHITECTURE.md`.
- Branch survey (`git ls-tree` on `main`, `docs`, both remotes): no
  phase reports, `ARCHITECTURE`, `DECISIONS`, or `DEMO` files
  on any branch — nothing to reconcile.
- No test suite was re-run for this audit: the changes are
  documentation-only (no code behavior changed), so there was nothing new
  for tests to catch. Backend `pytest` on a Docker-capable machine remains
  the outstanding item from the phase 5 frontend report.

## The one-liner version

| Piece | One-liner |
|---|---|
| `DEMO.md` | Every copy-paste command now points at a real address and a real script. |
| `ARCHITECTURE.md` | Status codes and endpoint addresses now say exactly what the code does. |
| `DECISIONS.md` | Checked against the code, needed nothing — left untouched. |
| Branch survey | No other phase reports existed outside `docs /`, so these stay the single truth. |

## What's next

- [ ] Run `docker compose exec backend pytest -v` on a Docker-capable machine (still outstanding from the phase 5 frontend report)
- [ ] Live demo pass: `docker compose up --build`, seed, submit the sector-7G order using the corrected tour
- [ ] Decide: commit everything (phase 5 reports, code, docs) as one commit or split per workstream
- [ ] Optional, out of scope: `README.md`'s demo curl has the same missing-`/api` bug — fix if wanted
