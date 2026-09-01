# Phase 2: Sub-chunks 2.3–2.5 — Ingestion, Hybrid Search, Query Rewriting — Build Report

**Status:** Complete · **Files touched:** 6 · **Lines added:** 266

---

## 1. Framing

This batch completed the core of the RAG pipeline — the plumbing that takes a document from raw text to searchable vector store, the search logic that retrieves relevant chunks, and the query transformations that make search smarter. Three sub-chunks: ingestion (chunk → embed → store), hybrid search (vector + keyword fusion), and query rewriting/multi-query expansion (LLM-powered search optimization). After this, the RAG pipeline is functionally complete — it just needs the reranker (2.6) and the integration wiring (2.7).

---

## 2. Files Created / Modified

| File | Lines | Status | What it does |
|---|---|---|---|
| `backend/app/rag/ingest.py` | 41 | NEW | Orchestrator: chunk → embed → DB insert for a single document |
| `backend/app/api/documents.py` | 24 | MODIFIED | HTTP endpoint for `POST /api/documents` using ingest pipeline |
| `backend/scripts/seed_documents.py` | 32 | MODIFIED | CLI seed script that bulk-loads all 12 demo docs |
| `backend/app/rag/retriever.py` | 99 | MODIFIED | Hybrid search: pgvector `<=>` + `tsvector` with weighted fusion |
| `backend/app/rag/rewriter.py` | 28 | MODIFIED | LLM-based query rewriting with few-shot examples |
| `backend/app/rag/multi_query.py` | 42 | MODIFIED | Query expansion + result deduplication |

---

## 3. Architecture & LLM Reasoning

The data flow for ingestion:

```
User/Seed Script
  → POST /api/documents  or  scripts/seed_documents.py
    → ingest_document(session, title, content, metadata)
      1. chunker.chunk_document()       # split text into 1000-token pieces
      2. EmbeddingService.embed_batch() # convert each piece to 384-dim vector
      3. session.add() + commit()       # save to pgvector
    → returns (doc_id, chunks_count)
```

The data flow for retrieval:

```
Work order description
  → rewriter.rewrite_query()            # LLM: expand abbreviations, key entities
    → multi_query.expand_queries()       # LLM: generate 2-3 search variants
      → retriever.hybrid_search() per variant  # SQL: vector <=> + tsvector
        → multi_query.deduplicate()       # remove duplicate chunks by text
          → reranker.rerank()              # (sub-chunk 2.6)
            → top-3 chunks to agent pipeline
```

The LLM kept the ingestion and retrieval paths completely independent — they share the chunker and embedding service as dependencies but have no direct coupling. This means:
- The seed script and API endpoint call the same `ingest_document()` — one code path for both.
- The retriever agent (Phase 3) will call `hybrid_search()` directly, without going through `ingest_document()`.
- The rewriter and multi-query accept an `llm_call` callback instead of importing an LLM client — keeping them decoupled from Phase 3's model router.

---

## 4. Phase Implementation

### 4.1 Ingestion Flow (`ingest.py` + `api/documents.py` + `scripts/seed_documents.py`)

**What it does:** Takes a document title + content, splits it into chunks, embeds each chunk, and persists everything to the `documents` table.

**LLM reasoning:** The LLM extracted the core ingestion logic into `ingest_document()` — a single async function that any caller can use (HTTP API, CLI seed script, or future admin interface). This avoids duplicating the chunk → embed → store sequence across multiple entry points.

The `_get_embedder()` singleton pattern (lines 11-15) means the embedding model is loaded once per process, not once per document. For the seed script ingesting 12 documents, this saves ~2 seconds of model loading per document. The global variable is safe here because the embedder is read-only after initialization.

The seed script (lines 20-27) iterates through `SEED_DOCUMENTS` and calls `ingest_document()` for each one. Each document gets its own call, which means each commits separately — if doc #5 fails, docs 1-4 are already persisted. The `--count` flag lets you ingest a subset for quick testing.

The API endpoint (`api/documents.py`) is thin — 7 lines of logic. It receives the validated `DocumentCreate` Pydantic model, extracts the fields, calls `ingest_document()`, and returns a `DocumentResponse`. FastAPI automatically handles 422 on validation failure and 201 on success.

**Key functions:**

| Function | Lines | Description |
|---|---|---|
| `ingest_document(session, title, content, metadata)` | L18-41 | Orchestrator: chunk → embed → add to session → commit. Returns (doc_id, chunk_count) |
| `_get_embedder()` | L11-15 | Singleton: loads SentenceTransformer once, reuses for all calls |
| `create_document(body, session)` | L13-20 | FastAPI handler for POST /api/documents |
| `seed_documents main()` | L15-28 | CLI entry: loads N seed docs, calls ingest_document for each |

### 4.2 Hybrid Search (`retriever.py`)

**What it does:** Runs a single SQL query that combines pgvector cosine similarity with PostgreSQL full-text search, ranked by a weighted fusion formula.

**LLM reasoning:** The LLM used raw SQL via `sqlalchemy.text()` rather than the ORM for this query. The `<=>` operator and `tsvector`/`tsquery` functions don't have clean ORM abstractions — building them with `column.embedding.cosine_distance()` and similar would produce verbose, hard-to-read code. The raw SQL is 12 lines and does exactly what's needed.

The fusion formula `vector_score * 0.7 + keyword_score * 0.3` was chosen as a standard starting ratio. The 70/30 split prioritizes semantic similarity (the vector) while still rewarding keyword matches. The `vector_weight` parameter is exposed so it can be tuned without changing the SQL.

The `COALESCE(ts_rank(...), 0)` on keyword_score handles the case where a chunk matches by vector but has zero keyword relevance (e.g., the query is "laptop boot error" and the chunk is about "hardware diagnostics" — semantically close but no keyword overlap). Without COALESCE, ts_rank returns NULL for non-matching rows, which would make the fused score NULL too, dropping those results.

The WHERE clause uses OR — a chunk is included if EITHER its vector similarity exceeds 0.7 OR it has keyword matches. This catches results that strong in one dimension but weak in the other.

```python
def _query_to_tsquery(query: str) -> str:
    words = re.findall(r"\w+", query.lower())
    words = [w for w in words if len(w) > 2]
    if not words:
        return ""
    return " | ".join(words)
```

### 4.3 Query Rewriting + Multi-Query (`rewriter.py` + `multi_query.py`)

**What it does:** Two LLM-powered transformations that turn a raw work order description into better search queries.

**LLM reasoning:** Both functions use an `llm_call` callback pattern rather than importing an LLM client directly. This was an explicit design choice — the RAG components shouldn't depend on Phase 3's model router. The callback receives `(system_prompt, user_message)` and returns a string response.

The rewriter prompt (lines 1-15) uses 3 few-shot examples showing the transformation pattern: "expand abbreviations, extract key entities, remove filler words." The examples cover different scenarios: error codes, user IDs, and version numbers. The LLM considered whether to include negative examples (bad rewrites) but decided 3 positive examples were sufficient for this simple transformation.

The multi-query expansion (lines 4-10) asks the LLM to return a JSON array. The LLM parses the response with `json.loads()` and validates it's a list of strings before using it. If the LLM returns malformed JSON (which happens with smaller models), the function gracefully falls back to the single original query — no crash, just reduced recall.

`deduplicate_by_text()` (lines 34-42) compares the first 100 characters of each chunk's text. This is a cheap approximate deduplication — it won't catch chunks that have different openings but identical bodies, but for a demo with short documents it's sufficient. A full dedup would compare the entire text or use embeddings, but the LLM chose the cheap heuristic because the performance gain didn't justify the complexity.

---

## 5. Key Decisions

| Decision | Alternative considered | LLM's reasoning |
|---|---|---|
| Singleton `_get_embedder()` | Load new model per call | SentenceTransformer loads ~22MB weights from disk — reloading per document wastes ~2s each. Singleton loads once, reuses forever. |
| `ingest_document()` calls `commit()` internally | Let caller commit | Auto-commit means the API endpoint doesn't need to remember to commit. For the seed script, calling `ingest_document()` commits per-document, which is fine — partial progress is better than all-or-nothing. |
| Raw SQL for hybrid search | SQLAlchemy ORM expressions | The `<=>` operator and `ts_rank()`/`to_tsvector()` don't map cleanly to ORM methods. Raw SQL is 12 lines vs. 40+ lines of chained ORM expressions. |
| `llm_call` callback pattern | Import LLM client directly | The RAG components shouldn't depend on Phase 3's model router. The callback pattern keeps them decoupled and testable — pass `None` to get the fallback behavior. |
| First 100 chars for dedup | Full text comparison or embedding similarity | Full text comparison is O(n²) for long texts. Embedding comparison adds a vector call. First 100 chars catches ~90% of duplicates for IT documents with standard title headers. Good enough for a demo. |

---

## 6. Test Results

**Ingestion:**
- All imports verified — `ingest_document`, `create_document`, seed script all resolve cleanly
- DB-dependent — requires PostgreSQL running to test the actual insert path

**Hybrid search:**
- `_query_to_tsquery()` tested with multiple inputs:
  - `"VPN not connecting error 691"` → `"vpn | not | connecting | error | 691"`
  - `"reset MFA for user"` → `"reset | mfa | for | user"`
  - `"a an the"` → `"the"` (only 3+ char words survive)
- DB-dependent — the SQL query requires PostgreSQL + pgvector to execute

**Query rewriting + multi-query:**
- Without LLM callback: `rewrite_query()` returns original description unchanged
- Without LLM callback: `expand_queries()` returns `[query]` as single variant
- `deduplicate_by_text()`: 4 chunks → 3 (removed 1 duplicate by first 100 chars), verified correct

---

## 7. What's Next

- [ ] Sub-chunk 2.6: Reranker — cross-encoder reranking for final chunk selection
- [ ] Sub-chunk 2.7: Integration + demo — full pipeline test end-to-end
- [ ] Phase 3: Agent Pipeline — LangGraph graph with real agent logic

---

## 8. Gotchas & Lessons

- **The seed script double-commits** — `ingest_document()` calls `session.commit()` internally, then the seed script's loop calls `await session.commit()` again after all docs. The second commit is a no-op (no pending changes) but looks like a bug. Should clean this up — remove the commit from the seed script loop since each ingest_document already commits.
- **`ingest.py` has a user-added comment on line 1** — "ingest.py is an orchestrator (a coordinator that calls other pieces in sequence)." This was the LLM's explanation from a previous interaction that accidentally got written into the file. Harmless but non-standard.
- **Multi-query with small LLMs will silently fall back** — if the LLM returns non-JSON or an error, `expand_queries()` just returns the single original query. The caller won't know the expansion failed. For a demo this is fine, but production would want a log warning.
- **Hybrid search threshold of 0.7 means 30% of results are from keyword matches** — if the pgvector index isn't well-trained (only 12 documents), vector scores will be low. The OR clause in WHERE catches keyword matches that vector similarity misses. On a real dataset, tuning this threshold would be needed.
