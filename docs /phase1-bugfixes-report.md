# Phase 1 Bugfixes — Build Report

**Status:** Complete · **Files touched:** 2 · **Lines changed:** 7

---

## 1. Framing

During Phase 1 validation (installing dependencies and running import tests against actual Python, not just static analysis), two runtime bugs surfaced that static `py_compile` checks missed. Both were type-level issues — the LLM wrote type annotations that looked correct but didn't match what the code actually did at runtime. These are exactly the kind of bugs you catch when you actually run the code versus just reading it.

---

## 2. Files Modified

| File | Lines | Change |
|---|---|---|
| `backend/app/core/cost_tracker.py` | 22 | Fixed `add_cost()` to accept `float` and `str` inputs, not just `Decimal` |
| `backend/app/db/models.py` | 97 | Renamed `metadata` column to `doc_metadata` to avoid SQLAlchemy reserved name conflict |

---

## 3. Architecture & LLM Reasoning

The bugs were unrelated — one in the cost tracking module, one in the ORM schema — but they share a common root cause: the LLM wrote type annotations that assumed perfect call-site discipline, without anticipating how the code would actually be used.

**Bug 1: `cost_tracker.py`** — The `add_cost(cost: Decimal)` method expected strictly `Decimal` objects. In practice, the values come from model router pricing tables (`float`), config settings (`float`), and potentially from API responses (`str`). The LLM wrote the annotation correctly for the internal implementation but didn't widen the input types to match real usage patterns.

**Bug 2: `db/models.py`** — The `DocumentChunk` class declared a column named `metadata`, which conflicts with SQLAlchemy's `DeclarativeBase.metadata` attribute. This is a well-known SQLAlchemy gotcha — `metadata` is reserved at the class level for the `MetaData` object that holds table/schema info. The LLM should have caught this during the initial generation but didn't because the column definition looks perfectly fine in isolation.

---

## 4. Bug Fix Implementation

### 4.1 CostTracker type widening

**What it does:** Allows `add_cost()` to accept `float` (from API pricing), `Decimal` (from calculations), and `str` (from config/env vars) without crashing.

**LLM reasoning:** The LLM evaluated two approaches:

1. **Accept only `Decimal`** — forces callers to convert. Cleaner internally but annoying to use. The model router `estimate_cost()` returns `Decimal`, config reads are `float`, status messages might carry `str`. Any caller that passes the wrong type crashes at runtime.

2. **Accept `Decimal | float | str` and normalize internally** — slightly messier signature but catches every input source. The conversion is one `Decimal(cost)` call.

The LLM chose approach 2 because the cost tracker sits at a boundary between multiple data sources (config, API responses, model router). Making it flexible prevents a class of silent crashes that would only surface when specific code paths exercise specific caller patterns.

```python
# Before (crashes with float or str input):
def add_cost(self, cost: Decimal):
    self.cumulative_cost += cost

# After (normalizes any numeric input):
def add_cost(self, cost: Decimal | float | str):
    self.cumulative_cost += Decimal(cost)
```

The same widening was applied to `__init__`'s `ceiling` parameter, which accepts config values that arrive as `float` from `pydantic-settings`.

### 4.2 SQLAlchemy `metadata` rename

**What it does:** Renames the `DocumentChunk.metadata` Python attribute to `doc_metadata` while keeping the underlying database column name as `metadata`.

**LLM reasoning:** SQLAlchemy's `DeclarativeBase` reserves the name `metadata` for its own use (the `MetaData` registry that tracks all tables, indexes, and schema objects). When a user-defined column uses the name `metadata`, SQLAlchemy raises an `InvalidRequestError` at class definition time — not at runtime, not at import, but at the moment the ORM processes the class.

The fix uses SQLAlchemy's column name override:

```python
# Before (crashes at ORM class load):
metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=dict)

# After (Python attribute != DB column name):
doc_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, default=dict)
```

The first argument `"metadata"` tells SQLAlchemy the DB column name is `metadata` even though the Python attribute is `doc_metadata`. Queries work the same way — `session.query(DocumentChunk).filter(DocumentChunk.doc_metadata["key"] == value)` — and the migration doesn't need to change because the migration already refers to the column by its database name.

---

## 5. Key Decisions

| Decision | Alternative considered | LLM's reasoning |
|---|---|---|
| `Decimal | float | str` on `add_cost()` | Strict `Decimal` only | The cost tracker is a boundary component that receives data from config files, model router calculations, and API responses. Each source uses a different type. Widening the input prevents a runtime crash that would be hard to trace — the first sign would be an agent step failing mid-pipeline with no obvious cause. |
| SQLAlchemy column name override (`"metadata"` as first arg) | Renaming the DB column to `doc_metadata` everywhere | Renaming the DB column would break the existing migration and affect raw SQL queries. The override keeps the DB schema unchanged while only changing the Python attribute name — zero migration changes needed. |

---

## 6. Test Results

The validation run exercises the full import chain:

```
All imports resolve OK
  Cheap: gemini-1.5-flash, Capable: gemini-1.5-pro
  CostTracker: forced_cheap=True, remaining=$0.00
  Pydantic models: order=Test, resolution.confidence=0.95
  ORM: 3 tables: orders, agent_traces, documents
  Enums: Priority=['low','medium','high','critical']
  Alembic: head=0001, 1 revision
```

- CostTracker tested with `float` (0.04), `str` ("0.02"), and `Decimal` — all accepted
- ORM models load without `InvalidRequestError`
- Alembic migration tree parsed successfully

---

## 7. What's Next

- [ ] Phase 2: RAG Pipeline — chunker, embedding, hybrid search, query rewriting, multi-query, reranker, seed documents
- [ ] Phase 3: Agent Pipeline — LangGraph graph with real agent logic

---

## 8. Gotchas & Lessons

- **Static analysis (`py_compile`) catches syntax errors but not type errors.** Both bugs passed `py_compile` fine — they only surfaced when Python actually executed the code. Type errors in business logic (Decimal vs float) and framework gotchas (SQLAlchemy reserved names) require actual execution to catch.
- **SQLAlchemy's `metadata` reservation is easy to miss** because it only applies to `DeclarativeBase` subclasses. A plain `Table` object wouldn't have this conflict. The error message from SQLAlchemy is clear but appears at import time, not at migration time — so a broken ORM class means the app won't even start.
- **The `cost_tracker.py` bug would have shown up in Phase 3** when the orchestrator's cost ceiling logic actually ran. Catching it now (during the Phase 1 validation pass) saved a debugging session later where the agent pipeline would mysteriously crash after budget enforcement kicked in.
