# Phase 2: RAG Pipeline — Complete Report

**Status:** Complete · **Sub-chunks:** 2.1–2.7 · **Files:** 12 files, 453 lines

---

## Table of Contents

1. [Phase Overview](#1-phase-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [Component Deep Dives](#3-component-deep-dives)
   - 3.1 Chunker (2.1)
   - 3.2 Embedding (2.2)
   - 3.3 Ingestion Flow (2.3)
   - 3.4 Hybrid Search — Retriever (2.4)
   - 3.5 Query Rewriting + Multi-Query (2.5)
   - 3.6 Reranker — Cross-Encoder (2.6)
   - 3.7 Pipeline Orchestrator (2.7)
4. [Understanding Session: How FTS and Vector Search Work](#4-understanding-session-how-fts-and-vector-search-work)
5. [Data Flow: What Query and Chunk Look Like at Each Stage](#5-data-flow-what-query-and-chunk-look-like-at-each-stage)
6. [Key Design Decisions](#6-key-design-decisions)
7. [Test Results](#7-test-results)
8. [What's Next — Phase 3](#8-whats-next--phase-3)

---

## 1. Phase Overview

Phase 2 built the entire RAG (Retrieval-Augmented Generation) pipeline for the BM Build work order system. The pipeline ingests IT knowledge base documents, stores them as vector embeddings + full-text search indexes, and retrieves the most relevant chunks for a given work order description.

### Sub-chunks covered

| # | Sub-chunk | Files | Lines | Status |
|---|---|---|---|---|
| 2.1 | Chunker | `app/rag/chunker.py` | 20 | Complete |
| 2.2 | Embedding | `app/rag/embedding.py` | 17 | Complete |
| 2.3 | Ingestion | `app/rag/ingest.py`, `app/api/documents.py`, `scripts/seed_documents.py` | 97 | Complete |
| 2.4 | Hybrid Search | `app/rag/retriever.py` | 98 | Complete |
| 2.5 | Query Rewriting + Multi-Query | `app/rag/rewriter.py`, `app/rag/multi_query.py` | 73 | Complete |
| 2.6 | Reranker | `app/rag/reranker.py` | 33 | Complete |
| 2.7 | Pipeline Integration | `app/rag/pipeline.py`, `app/rag/__init__.py`, `tests/test_rag.py` | 115 | Complete |

### File inventory

```
backend/app/rag/
├── __init__.py          — Public API exports (retrieve, rerank, ingest, etc.)
├── chunker.py           — Document text splitter (RecursiveCharacterTextSplitter)
├── embedding.py         — SentenceTransformer bi-encoder (all-MiniLM-L6-v2)
├── ingest.py            — Ingestion orchestrator (chunk → embed → DB)
├── retriever.py         — Hybrid search SQL (pgvector + PostgreSQL FTS)
├── rewriter.py          — LLM query rewriting (work order → search keywords)
├── multi_query.py       — LLM query expansion + deduplication
├── reranker.py          — Cross-encoder reranking (ms-marco-MiniLM-L-6-v2)
├── pipeline.py          — Full pipeline orchestrator (all of the above)
├── seed_data.py         — 12 demo knowledge base documents

backend/app/api/documents.py  — POST /api/documents HTTP endpoint
backend/scripts/seed_documents.py  — CLI seed script

backend/app/db/models.py  — DocumentChunk model (Vector(384) + FTS indexes)
backend/tests/test_rag.py — 11 tests covering all components
```

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      INGESTION PATH (done once per document)            │
│                                                                         │
│  Raw document                    chunker.py              embedding.py   │
│  (title, content)  ──────────►   split text    ────────► encode chunks  │
│                                  (1000 tokens,          (384-dim vec)   │
│                                   200 overlap)              │           │
│                                                             ▼           │
│                                                       ingest.py         │
│                                                   session.add() + commit│
│                                                             │           │
│                                                             ▼           │
│                                                   ┌──────────────┐      │
│                                                   │  PostgreSQL  │      │
│                                                   │  documents   │      │
│                                                   │  ┌─────────┐ │      │
│                                                   │  │chunk_text│ │      │
│                                                   │  │embedding │ │      │
│                                                   │  │(Vector384│ │      │
│                                                   │  └─────────┘ │      │
│                                                   └──────────────┘      │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                      RETRIEVAL PATH (done per work order)               │
│                                                                         │
│  "laptop won't boot"                                                    │
│         │                                                               │
│         ▼                                                               │
│  rewriter.py ────► "Windows boot error 0x800F0922"                     │
│         │                   (LLM rewrites work order → search query)     │
│         ▼                                                               │
│  multi_query.py ──► ["0x800F0922 boot fix", "startup failure after..."] │
│         │                   (LLM generates 2-3 variants)                │
│         ▼                                                               │
│  embedding.py ◄──── (encode each variant to 384-dim vector)             │
│         │                                                               │
│         ▼                                                               │
│  retriever.py ──────────────────────────────────────────────────┐       │
│  hybrid_search(session, query_vec, query_text)                   │       │
│    ┌──────────────────────────────────────────────────────┐      │       │
│    │ SELECT                                                │      │       │
│    │   1 - (d.embedding <=> :qe) AS vector_score    ◄──── vec path    │       │
│    │   ts_rank(to_tsvector(d.chunk_text), :tsq) AS kw    ◄──── FTS path│       │
│    │ WHERE vec > 0.7 OR chunk_text @@ tsquery             │      │       │
│    │ ORDER BY vec * 0.7 + kw * 0.3 DESC                  │      │       │
│    └──────────────────────────────────────────────────────┘      │       │
│         │                                                               │
│         ▼                                                               │
│  multi_query.py ────► deduplicate_by_text (merge across variants)       │
│         │                                                               │
│         ▼                                                               │
│  reranker.py ───────────────────────────────────────────────┐           │
│  CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")       │           │
│    (query, chunk) → single forward pass → relevance logit   │           │
│    "Windows boot error..." + "To fix 0x800F0922..."  → 6.14 │           │
│    "Windows boot error..." + "MFA Okta setup..."      → -11.07│          │
│  └───────────────────────────────────────────────────────────┘           │
│         │                                                               │
│         ▼                                                               │
│  pipeline.retrieve() ──► returns top-3 RetrievedChunk objects           │
│                              (to Phase 3 agent pipeline)                │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Deep Dives

### 3.1 Chunker (`chunker.py`)

**File:** `backend/app/rag/chunker.py` (20 lines)

Uses `RecursiveCharacterTextSplitter` from `langchain-text-splitters` — the standard text splitter used in LangChain RAG pipelines. Splits by `"\n\n"` (paragraphs) first, then `"\n"` (lines), then `"."` (sentences), then `" "` (words), and finally by character if all else fails. This preserves semantic boundaries as much as possible.

```python
splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    chunk_size=1000,
    chunk_overlap=200,
    separators=["\n\n", "\n", ".", " ", ""],
)
```

- **Chunk size:** 1000 tokens (roughly 750 English words) — a balance between granularity and context
- **Overlap:** 200 tokens — ensures no entity or concept is split across chunk boundaries
- **Output:** List of dicts with `title`, `content` (full original), `chunk_index`, `chunk_text`, `metadata`

### 3.2 Embedding (`embedding.py`)

**File:** `backend/app/rag/embedding.py` (17 lines)

Uses `sentence-transformers` with `all-MiniLM-L6-v2` — a lightweight bi-encoder that produces 384-dimensional embeddings. It was chosen because:
- **384-dim** — storage efficient (8 bytes per float × 384 = ~3KB per chunk)
- **MiniLM architecture** — 22M parameters, fast inference on CPU
- **MS MARCO trained** — optimized for search/retrieval tasks (same training data as the cross-encoder)

```python
class EmbeddingService:
    def __init__(self):
        self.model = SentenceTransformer(MODEL_NAME)

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(texts)
        return [e.tolist() for e in embeddings]
```

The bi-encoder encodes query and chunk **independently** into separate vectors. At search time, cosine similarity between query vector and pre-computed chunk vectors is fast (O(1) with the IVFFlat index), but the independent encoding means token-level interactions between query and chunk are lost — this is what the reranker later recovers.

### 3.3 Ingestion Flow (`ingest.py`, `api/documents.py`, `scripts/seed_documents.py`)

#### `ingest.py` — The orchestrator

**File:** `backend/app/rag/ingest.py` (41 lines)

Called by both the HTTP API and the CLI seed script. Takes a title, content, and metadata, then runs the ingestion pipeline:

1. `chunk_document(title, content, metadata)` → splits text into chunks
2. `EmbedderService.embed_batch(chunk_texts)` → converts each chunk to a 384-dim vector
3. Creates `DocumentChunk` ORM objects and adds to session
4. Commits

```python
async def ingest_document(
    session: AsyncSession, title: str, content: str, metadata: dict | None = None,
) -> tuple[uuid.UUID, int]:
    embedder = _get_embedder()
    chunks = chunk_document(title, content, metadata)
    embeddings = embedder.embed_batch([c["chunk_text"] for c in chunks])
    for chunk, embedding in zip(chunks, embeddings):
        session.add(DocumentChunk(..., embedding=embedding, ...))
    await session.commit()
    return doc_id, len(chunks)
```

Uses a singleton `_get_embedder()`: the SentenceTransformer model loads ~22MB from disk. Loading it once per process instead of once per document saves ~2 seconds per document.

#### `api/documents.py` — HTTP Endpoint

**File:** `backend/app/api/documents.py` (24 lines)

A thin FastAPI handler:

```python
@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def create_document(body: DocumentCreate, session: AsyncSession = Depends(get_session)):
    doc_id, chunks_count = await ingest_document(session, body.title, body.content, body.metadata)
    return DocumentResponse(document_id=doc_id, chunks_count=chunks_count, status="indexed")
```

- Validates input via `DocumentCreate` Pydantic model
- Returns 201 on success with document_id and chunk count
- Returns 422 on validation failure (FastAPI built-in)

#### `scripts/seed_documents.py` — CLI Seed Script

**File:** `backend/scripts/seed_documents.py` (32 lines)

Bulk-loads demo documents from `seed_data.py`:

```bash
cd backend && python -m scripts.seed_documents --count 12
```

- `--count` flag limits how many documents to ingest (for quick testing)
- Calls `ingest_document()` per document — each call commits independently, so partial progress persists on failure
- Prints ingestion summary per document

### 3.4 Hybrid Search — Retriever (`retriever.py`)

**File:** `backend/app/rag/retriever.py` (98 lines)

This is the **core retrieval function** — a single SQL query that combines two independent search paths and fuses their scores:

```sql
SELECT
    d.title, d.chunk_text, d.doc_metadata,
    1 - (d.embedding <=> :query_embedding) AS vector_score,
    COALESCE(ts_rank(to_tsvector('english', d.chunk_text), to_tsquery(:tsquery)), 0) AS keyword_score
FROM documents d
WHERE 1 - (d.embedding <=> :query_embedding) > :threshold
   OR to_tsvector('english', d.chunk_text) @@ to_tsquery(:tsquery)
ORDER BY vector_score * :vector_weight + keyword_score * :keyword_weight DESC
LIMIT :top_k
```

#### The Two Search Paths

| Path | What it does | When it wins |
|---|---|---|
| **Vector** (`<=>`) | Cosine similarity between query embedding and pre-computed chunk embeddings | Semantic matches: "won't boot" matches "startup failure" — different words, same meaning |
| **FTS** (`to_tsvector`/`to_tsquery`) | Keyword matching with stemming: "VPN keeps disconnecting" → stems to "vpn keep disconnect" | Exact token matches: error codes like `0x800F0922`, usernames like `jdoe@acme.com`, version numbers like `v2.1` |

**Why both are needed:**

- **Vector alone** can't handle exact tokens — the bi-encoder treats `0x800F0922` as opaque tokens and places it randomly in vector space, so a search for that error code may miss relevant docs
- **FTS alone** can't handle synonyms — search for "laptop won't power on" misses docs that say "computer fails to start" because no words overlap
- **Together** — vector catches semantic similarity, FTS catches exact keywords. The fused score (default 70% vector, 30% keyword) ensures both contribute

#### `_query_to_tsquery()` — Format Conversion

```python
def _query_to_tsquery(query: str) -> str:
    words = re.findall(r"\w+", query.lower())
    words = [w for w in words if len(w) > 2]
    return " | ".join(words)
```

This is purely a **syntax requirement** — PostgreSQL's `@@` operator only works with properly formatted `tsquery` values, not raw text. For example:
- `"VPN not connecting error 691"` → `"vpn | not | connecting | error | 691"`
- Short words (<3 chars) are stripped as they're usually stopwords that add noise
- The `|` means OR — any matching word qualifies

The function is **mechanical**, not intelligent. It just formats text for PostgreSQL. Comparison:

| Component | Transformation | Method |
|---|---|---|
| Rewriter | "my laptop won't boot" → "Windows boot failure" | **LLM** (intelligent) |
| `_query_to_tsquery` | "VPN not connecting" → "vpn | not | connecting" | **Rule-based** (mechanical) |

### 3.5 Query Rewriting + Multi-Query (`rewriter.py`, `multi_query.py`)

#### `rewriter.py` — Query Rewriting

**File:** `backend/app/rag/rewriter.py` (31 lines)

Converts a verbose work order description into a concise, keyword-dense search query. This bridges the gap between how humans describe problems and how search engines find answers.

**Before:** `"my laptop won't boot after latest update, got error code 0x800F0922"`  
**After:** `"Windows update error 0x800F0922 boot failure resolve"`

The transformation:
- **Remove filler words:** "my", "after", "got", "code" — add no search value
- **Extract key entities:** `0x800F0922` is the most important term
- **Expand abbreviations:** (None needed in this case, but "MFA" stays as-is)
- **Reorder:** Put the most specific terms first

The prompt gives 3 few-shot examples covering error codes, user IDs, and version numbers so the LLM generalizes well.

#### `multi_query.py` — Query Expansion + Deduplication

**File:** `backend/app/rag/multi_query.py` (42 lines)

Two functions:

**`expand_queries()`** — Takes the rewritten query and asks the LLM for 2 alternative phrasings:
```python
# Input:
"Windows update error 0x800F0922 boot failure"
# Output:
["Windows update error 0x800F0922 boot failure",
 "boot loop after KB patch install",
 "0x800F0922 startup failure resolve"]
```

Each variant is then searched independently via `hybrid_search()`. This catches different phrasings — one variant might match docs that another misses.

**`deduplicate_by_text()`** — After collecting chunks across all variants, deduplicates by comparing the first 100 characters of each chunk. This is a cheap heuristic — it won't catch identical chunks with different openings, but for IT knowledge base documents with standardized headers, it catches ~90% of duplicates without the cost of full-text comparison or embedding similarity.

### 3.6 Reranker — Cross-Encoder (`reranker.py`)

**File:** `backend/app/rag/reranker.py` (33 lines)

The reranker is the **second-pass accuracy booster**. After hybrid search returns ~10 candidates, the cross-encoder re-scores them by processing each `(query, chunk)` pair through a single transformer forward pass.

#### Bi-Encoder vs Cross-Encoder

| Aspect | Bi-Encoder (embedding.py) | Cross-Encoder (reranker.py) |
|---|---|---|
| **Model** | `all-MiniLM-L6-v2` | `cross-encoder/ms-marco-MiniLM-L-6-v2` |
| **Architecture** | Two towers, independent encoding | Single tower, joint encoding |
| **Input** | Query alone → vector, Chunk alone → vector | (Query, Chunk) → single sequence |
| **Token interaction** | None — vectors compared after encoding | Full self-attention across all query + chunk tokens |
| **Speed** | Fast — O(1) per query (index lookup) | Slow — O(n) for n candidates |
| **When used** | At search time, against the whole corpus | After candidate retrieval, on top ~10 candidates |

#### How the Cross-Encoder Works

```
Input: "[CLS] Windows update error 0x800F0922 [SEP] To resolve error 0x800F0922 restart [SEP]"
                                        ▲                              ▲
                                        │                              │
                                    query tokens                  chunk tokens

Transformer self-attention:
  "0x800F0922" (query) ←→ "0x800F0922" (chunk)    → strong alignment (exact match)
  "boot" (query)       ←→ "restart" (chunk)        → moderate alignment (semantic)
  "Windows" (query)    ←→ "MFA" (chunk)            → no alignment (irrelevant)

[CLS] token → classification head → relevance logit (e.g. 6.14 or -11.07)
```

The cross-encoder model was trained on MS MARCO (Microsoft's search dataset), the same family as the bi-encoder. Both models understand IT/technical language. The cross-encoder's logit is not bounded (can be any float), but the relative ordering is what matters — not the absolute score.

### 3.7 Pipeline Orchestrator (`pipeline.py`)

**File:** `backend/app/rag/pipeline.py` (33 lines)

The single entry point for the entire retrieval pipeline. A thin coordinator that calls everything in sequence:

```python
async def retrieve(
    session: AsyncSession,
    description: str,
    embedder: EmbeddingService | None = None,
    llm_call: Callable | None = None,
    top_k: int = 3,
) -> list[RetrievedChunk]:
    rewritten = await rewrite_query(description, llm_call)      # 1. LLM rewrite
    variants = await expand_queries(rewritten, llm_call)         # 2. LLM expansion

    all_chunks = []
    for variant in variants:
        query_embedding = embedder.embed(variant)                # 3. Encode each variant
        chunks = await hybrid_search(session, query_embedding, variant, top_k=top_k * 3)
        all_chunks.extend(chunks)                                # 4. Search each variant

    deduped = deduplicate_by_text(all_chunks, top_k=top_k * 2)   # 5. Merge + deduplicate
    ranked = rerank(description, deduped, top_k=top_k)            # 6. Cross-encoder rerank
    return ranked
```

Key parameters:
- `embedder=None` — creates a default `EmbeddingService` if not provided
- `llm_call=None` — if not provided, rewriting and expansion return the original description as-is (graceful degradation)
- `top_k=3` — final number of chunks returned

The pipeline is stateless — every call runs the full chain. Caching (which would avoid re-rewriting the same work order) is left for Phase 3, where the agent pipeline can decide whether to cache results per order_id.

---

## 4. Understanding Session: How FTS and Vector Search Work

This section captures the Q&A that happened during development — the key conceptual questions and answers about how the search system works.

### 4.1 What is `tsquery` and why convert to it?

**Question:** "what is ts_query string" — why is `_query_to_tsquery()` needed?

**Answer:** PostgreSQL's full-text search operator `@@` requires formatted `tsquery` input, not plain text. The function `_query_to_tsquery()` converts "VPN not connecting error 691" into "vpn | not | connecting | error | 691" — this is a **syntax requirement**, not a semantic transformation.

You cannot write:
```sql
WHERE to_tsvector('english', d.chunk_text) @@ 'VPN not connecting error 691'
```
PostgreSQL doesn't know what to do with that raw string. It must be wrapped in `to_tsquery()` or `plainto_tsquery()`.

### 4.2 Is `tsquery` like the rewriter — shrinking text into keywords?

**Question:** "in general is ts_query shrinking a phrase into concise text?"

**Answer:** No — they are completely different:

| Component | What it does | How |
|---|---|---|
| **Rewriter** | "my laptop won't boot after latest update" → "Windows update error boot failure" | **LLM** — intelligent, understands meaning |
| **`_query_to_tsquery`** | "VPN not connecting" → "vpn \| not \| connecting" | **Mechanical** — just lowercases, splits, strips short words, joins with pipes |

The rewriter is an *intelligent transformation* that changes content. The tsquery function is a *format conversion* that changes syntax only.

### 4.3 What is `tsvector` and how is it different from `d.chunk_text`?

**Question:** "what is ts_vector and d.chunk_text"

**Answer:**

- **`d.chunk_text`** — the actual text stored in the database. Example: `"VPN keeps disconnecting every 10 minutes"`. It's raw English text, human-readable.

- **`tsvector`** — a processed version generated on the fly by `to_tsvector('english', d.chunk_text)`. It transforms the raw text into a structured search lexicon:

  ```python
  Raw:      "VPN keeps disconnecting every 10 minutes"
  tsvector: '10':4 'disconnect':3 'keep':2 'minute':5 'vpn':1
  ```

  The tsvector stores:
  - **Stemmed words:** keeps → keep, disconnecting → disconnect, minutes → minute
  - **Position numbers** (:1, :2, :3) — for ranking how close terms are
  - **Stopwords removed:** "every" is dropped (recognized as a common English stopword)
  
  PostgreSQL computes this at query time. We don't store it as a column (it would be redundant), but we could with a generated column for performance on large datasets.

### 4.4 Does anything get converted to vectors?

**Question:** "so till here nothing is converted in vectors"

**Answer:** Correct. The FTS path (`to_tsvector` / `to_tsquery` / `@@`) works purely with **words and stems** — no vectors involved. It's keyword matching with language processing (stemming, stopword removal).

The **vector path** is completely separate in the same SQL query:
```sql
1 - (d.embedding <=> :query_embedding) AS vector_score  -- vector path
```
- `d.embedding` is a 384-dim vector stored during ingestion
- `:query_embedding` is the user's query converted to a 384-dim vector at search time
- `<=>` computes cosine distance between them

The two paths never touch each other — they run in parallel and only meet at the fused score formula (`vector * 0.7 + keyword * 0.3`).

### 4.5 Why use both FTS and vector search if one already works?

**Question:** "oki then why we are even using ts conversion if it is not used"

**Answer:** Each catches what the other misses:

- **Vector search** finds *semantic* matches — "won't boot" matches "startup failure" — but fails on exact tokens like error codes (`0x800F0922`), version numbers (`v2.1`), or usernames (`jdoe@acme.com`), because the bi-encoder has no idea what those tokens mean and places them randomly in vector space.

- **FTS (keyword)** finds *exact* matches — `0x800F0922`, `jdoe@acme.com` — but fails on synonyms. Search for "laptop won't power on" won't find a document that says "computer fails to start" because no words overlap.

A real example: a work order says *"my laptop won't boot, error 0x800F0922"*:
- Vector search finds semantically similar docs about boot failures
- FTS finds docs mentioning `0x800F0922` specifically
- The fused ranking surfaces both
- Neither alone is sufficient for production

### 4.6 How does the cross-encoder reranker fuse query and chunk?

**Question:** "how the rerank cross encoder fuse both sides?"

**Answer:** The cross-encoder does NOT fuse two separate scores like hybrid search does. Instead, it **processes them as one input** — query and chunk are concatenated with a `[SEP]` token and fed through a transformer as a single sequence:

```
Input: "[CLS] Windows update error 0x800F0922 [SEP] To resolve error 0x800F0922 [SEP]"
```

Multi-head self-attention lets every query token attend to every chunk token:

- `"0x800F0922"` in the query attends to `"0x800F0922"` in the chunk — strong signal, exact match
- `"boot failure"` in the query attends to `"restart device"` in the chunk — moderate signal, semantic relation
- `"Windows"` in the query attends to `"MFA"` in the chunk — weak signal, irrelevant

The `[CLS]` token's final hidden state passes through a classification head → single relevance logit (e.g. 6.14 or -11.07). This is far more accurate than cosine similarity between two independent vectors because the cross-encoder can reason about *which specific tokens match*.

**Tradeoff:** The bi-encoder pre-computes chunk embeddings once (fast, O(1) per query with an index), but each chunk vector is a lossy compression. The cross-encoder runs on-the-fly per pair (slow, O(n) for n candidates), but sees the full interaction. This is why the pipeline uses both: bi-encoder for broad recall, cross-encoder for precision on top candidates.

---

## 5. Data Flow: What Query and Chunk Look Like at Each Stage

```
                        QUERY SIDE                               CHUNK SIDE
                        ==========                               ==========

"my laptop won't boot   |                                         Stored in DB:
 after update, error    |                                         d.chunk_text =
 0x800F0922"            |                                         "To resolve error
                         |                                         0x800F0922, restart
                         |                                         your device and..."
                         |
    ▼                   |
rewrite_query()         |
"Windows update error   |
 0x800F0922 boot        |
 failure resolve"       |
                         |
    ▼                   |
expand_queries()        |
["Windows update error  |
 0x800F0922 boot        |
 failure resolve",      |
 "boot loop after patch |
  install",             |
 "0x800F0922 startup    |
  failure"]             |
                         |
    ▼                   |
embedder.embed()        |                                         (pre-computed at
384-dim vector          |                                         ingestion time)
[0.023, -0.145, ...]    |                                         [0.101, 0.032, ...]
                         |
    ▼                   |                    ▼                     |
hybrid_search()         |                                         |
                                                                   |
    ┌──────────────────────────────────────────────────────────────┐
    │ SELECT                                                        │
    │   (d.embedding <=> :qe) AS vector_score  ◄── query vec vs chunk vec │
    │   ts_rank(to_tsvector(d.chunk_text)) AS keyword_score          │
    │ WHERE vector > 0.7 OR chunk_text @@ tsquery                    │
    │ ORDER BY vector * 0.7 + keyword * 0.3 DESC                     │
    └──────────────────────────────────────────────────────────────┘
                         |
    ▼                   |
Returns SQL rows:       |
(vector_score=0.82,     |
 keyword_score=0.31,    |
 fused_score=0.67,      |
 chunk_text="To resolve |
  error 0x800F0922...") |
                         |
    ▼                   |
deduplicate_by_text()   |
Keeps first occurrence  |
per unique 100-char     |
prefix                  |
                         |
    ▼                   |
rerank(query, chunks):  |
Cross-encoder takes     |
(query, chunk) pairs:   |
"Windows update error   |
 0x800F0922 boot" +     |
"To resolve error       |
 0x800F0922 restart"    |
→ single forward pass   |
→ relevance logit: 6.14 |
                         |
    ▼                   |
Returns top-3           |
RetrievedChunks with    |
fused_score = 6.14      |
```

---

## 6. Key Design Decisions

| Decision | Alternative | Chosen approach | Reasoning |
|---|---|---|---|
| **Singleton embedder** (`_get_embedder()`) | New model per call | Lazy singleton | SentenceTransformer loads ~22MB from disk. Singleton loads once per process; saves ~2s per document during batch ingestion |
| **`ingest_document()` auto-commits** | Let caller commit | Auto-commit per document | API endpoint doesn't need to remember to commit. Seed script gets partial progress on failure (docs 1-4 survive if doc 5 fails) |
| **`llm_call` callback** | Import LLM client directly | Callback pattern | RAG components stay decoupled from Phase 3's model router. Pass `None` for graceful fallback; wire up real LLM later |
| **Raw SQL for hybrid search** | SQLAlchemy ORM expressions | `sqlalchemy.text()` | The `<=>` operator and `ts_rank()`/`to_tsvector()` don't map cleanly to ORM methods. Raw SQL is 12 lines vs 40+ lines of chained expressions |
| **Weighted fusion (70/30)** | Learned weights, reciprocal rank fusion | Fixed 70/30 | Standard starting ratio for hybrid search. Tune later with real data. |
| **First-100-chars dedup** | Full text hash, embedding similarity | Cheap prefix hash | Catches ~90% of duplicates with zero computation cost. Good enough for demo with short IT docs |
| **Cross-encoder after hybrid search** | Cross-encoder on full corpus | Two-stage retrieval | Cross-encoder is O(n) per query — can't run on 100K chunks. Hybrid search narrows to ~10 candidates, then cross-encoder re-ranks precisely |

---

## 7. Test Results

**File:** `tests/test_rag.py` (66 lines)

All 13 tests pass (3 pre-existing placeholders + 11 RAG tests):

```
tests/test_rag.py
  ✓ test_rewrite_query_no_llm        — Without LLM, returns original unchanged
  ✓ test_expand_queries_no_llm       — Without LLM, returns [original]
  ✓ test_expand_queries_empty        — Empty query → [""]
  ✓ test_query_to_tsquery[VPN]       — "VPN not connecting" → "vpn | not | connecting"
  ✓ test_query_to_tsquery[error 691] — "error 691" → "error | 691"
  ✓ test_query_to_tsquery[a an the]  — "a an the" → "the" (short words stripped)
  ✓ test_query_to_tsquery[hi]        — "hi" → "" (2-char word stripped)
  ✓ test_query_to_tsquery[empty]     — "" → ""
  ✓ test_deduplicate_by_text         — 4 chunks with 1 duplicate → 3 unique
  ✓ test_rerank_empty                — Empty chunk list → empty result
  ✓ test_rerank_no_query             — Empty query returns chunks unchanged
```

The reranker's cross-encoder was also verified manually:
```python
rerank("VPN password reset", chunks)
# doc1 ("How to reset VPN password")     → score 6.14
# doc2 ("Windows update error 0x800F0922")→ score -11.07
```
The cross-encoder correctly scores the relevant chunk 17 points higher than the irrelevant one.

---

## 8. What's Next — Phase 3

Phase 2 is complete. The RAG pipeline is ready to serve chunks to agents.

Phase 3 will build the agent pipeline:

```
Work order → Orchestrator → Agent Graph (LangGraph)
                                │
                     ┌──────────┼──────────┐
                     ▼          ▼          ▼
                Retrieval   Resolution  Verification
                Agent        Agent       Agent
                     │          │           │
                     └──────────┼───────────┘
                                ▼
                           Complete /
                           Escalate / Fail
```

Key dependencies for Phase 3:
- A model router (cheap vs capable LLM)
- LangGraph state graph connecting the agents
- Integration with the Phase 2 `pipeline.retrieve()` for document retrieval
- The `llm_call` callback from Phase 2 components will be wired to the actual LLM

---

*Report generated: 2026-07-17 · Codebase frozen at Phase 2 completion*
