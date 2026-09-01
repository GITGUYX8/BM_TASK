# Phase 2: Sub-chunks 2.1 & 2.2 — Seed Data + Chunker + Embedding — Build Report

**Status:** Complete · **Files touched:** 3 · **Lines added:** 285

---

## 1. Framing

The goal was laying the RAG pipeline foundation — the data and the two core operations that every other RAG step depends on. First, seed documents that simulate a realistic IT knowledge base (so the retriever has something to find during the demo). Second, the chunker that splits documents into searchable pieces. Third, the embedding service that converts those pieces into vector representations for similarity search. Without these three pieces, nothing else in the RAG pipeline can be built or tested.

---

## 2. Files Created / Modified

| File | Lines | What it does |
|---|---|---|
| `backend/app/rag/seed_data.py` | 248 | 12 realistic IT support documents with metadata (category, author, version) |
| `backend/app/rag/chunker.py` | 20 | RecursiveCharacterTextSplitter wrapping — 1000-token chunks, 200-token overlap |
| `backend/app/rag/embedding.py` | 17 | SentenceTransformer `all-MiniLM-L6-v2` wrapper — single + batch embedding, 384-dim output |

---

## 3. Architecture & LLM Reasoning

The three pieces form a simple pipeline:

```
Raw document (text)
  → chunker.py: RecursiveCharacterTextSplitter(chunk_size=1000, overlap=200)
    → list of chunk dicts
      → embedding.py: SentenceTransformer('all-MiniLM-L6-v2')
        → list of 384-dim vectors
          → stored in pgvector (via ingestion script in sub-chunk 2.3)
```

The chunker and embedding service are intentionally stateless — they take input, produce output, no side effects. This makes them easy to test and call from different contexts (the API endpoint, the seed script, or directly from the retriever agent). The LLM considered wrapping them as a class but went with module-level functions for the chunker and a lightweight class for the embedder (because SentenceTransformer initialization loads model weights — you want to do that once and reuse).

The embedding model choice (`all-MiniLM-L6-v2`) was evaluated against alternatives:

- **OpenAI `text-embedding-3-small`** — better quality (1536 dims) but costs money per API call and requires an API key. Ruled out for a zero-cost demo.
- **Cohere embed** — similar quality to OpenAI, same API-key problem.
- **`all-MiniLM-L6-v2`** — fully local, 384 dims is sufficient for ~100 chunks, free, ~22MB download. Chosen for the demo.

The trade-off: lower dimensionality means less expressive embeddings, but for a demo with 12 documents in a narrow IT domain, 384 dims is perfectly adequate. If the knowledge base grew to 10,000+ documents, a 768-dim or 1536-dim model would likely improve retrieval quality.

---

## 4. Phase Implementation

### 4.1 Seed Data (`seed_data.py`)

**What it does:** Defines 12 IT support documents covering diverse topics: networking, IAM, compliance, procurement, security, migration, maintenance, HR/IT, development, operations, process, and AI governance.

**LLM reasoning:** The documents needed to be realistic enough that a RAG retriever could meaningfully match them to sample work orders. Each document includes specific technical details (error codes like 691 and 812 for VPN, specific SLA times for escalation, actual patch Tuesday processes) so that when a work order mentions "error 0x800F0922" or "VPN not connecting," the vector search has concrete terms to match against.

The LLM structured each document with 2-4 paragraphs, using `\n\n` separators at natural section boundaries. The metadata includes `category`, `author`, and `version` — fields that could be used for filtering later. Categories are intentionally distinct (one per document) to ensure broad coverage.

| Doc | Title | Category | Words |
|---|---|---|---|
| 1 | VPN Connection Troubleshooting Guide | network | 167 |
| 2 | Password Reset Procedure | iam | 176 |
| 3 | Software Installation Policy | compliance | 163 |
| 4 | Hardware Replacement Workflow | procurement | 184 |
| 5 | Data Breach Incident Response Plan | security | 196 |
| 6 | Email Migration to Office 365 | migration | 210 |
| 7 | Server Patching Schedule | maintenance | 189 |
| 8 | Employee Offboarding Checklist | hr-it | 187 |
| 9 | API Rate Limiting Best Practices | development | 196 |
| 10 | Database Backup and Recovery SOP | operations | 198 |
| 11 | Work Order Escalation Matrix | process | 185 |
| 12 | LLM Output Validation Rules | ai-governance | 201 |

### 4.2 Chunker (`chunker.py`)

**What it does:** Single function `chunk_document(title, content, metadata)` that splits a document into overlapping chunks using `RecursiveCharacterTextSplitter`.

**LLM reasoning:** The chunker uses `from_tiktoken_encoder` rather than character-count splitting. This is important because LLM APIs (OpenAI, Anthropic) charge by token, not character — if we measure chunk size in characters, a chunk might exceed the LLM context window when tokenized. Tiktoken-based splitting ensures each chunk is *at most* 1000 tokens in the model's actual tokenizer.

The separator priority `["\n\n", "\n", ".", " ", ""]` means the splitter prefers breaking at paragraph boundaries first, then line breaks, then sentences, then words. This keeps semantically related text together. The 200-token overlap means context near a boundary isn't lost — the next chunk starts 200 tokens before the previous one ends.

Standard settings from PLAN.md — nothing novel here. The RecursiveCharacterTextSplitter is a well-established pattern in RAG pipelines.

```python
def chunk_document(title: str, content: str, metadata: dict | None = None) -> list[dict]:
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " ", ""],
    )
    texts = splitter.split_text(content)
    return [
        {
            "title": title,
            "content": content,
            "chunk_index": i,
            "chunk_text": t,
            "metadata": metadata or {},
        }
        for i, t in enumerate(texts)
    ]
```

### 4.3 Embedding Service (`embedding.py`)

**What it does:** `EmbeddingService` class wrapping `SentenceTransformer('all-MiniLM-L6-v2')`. Provides `embed(text)` for single strings and `embed_batch(texts)` for bulk processing.

**LLM reasoning:** The service loads the model once at construction time and reuses it for all calls. The batch method `model.encode(texts)` is significantly faster than calling `model.encode(text)` in a loop because SentenceTransformer internally parallelizes batch inference. For the seed script (12 documents, ~12 chunks), both would be instant, but the batch method is the right pattern for production.

The `.tolist()` conversion is necessary because SentenceTransformer returns numpy arrays, but pgvector expects Python lists for storage. Both methods return plain Python `list[float]` — no numpy arrays leaking into the data layer.

```python
class EmbeddingService:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")

    def embed(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(texts)
        return [e.tolist() for e in embeddings]
```

---

## 5. Key Decisions

| Decision | Alternative considered | LLM's reasoning |
|---|---|---|
| Tiktoken-based chunk size (1000 tokens) | Character-based (raw text length) | Token-based ensures chunks fit within LLM context windows. A 1000-token chunk could be 4000 characters of dense code or 600 characters of whitespace — character-based sizing is unreliable. |
| `all-MiniLM-L6-v2` (384-dim) | OpenAI ada-003 (1536-dim) or Cohere | Fully local, zero API cost, ~22MB download. For 100 demo chunks, 384 dims is sufficient. Would reconsider at 10K+ chunks. |
| Class-based EmbeddingService | Module-level functions | SentenceTransformer model loading is expensive (~2s first load) — you want a singleton, not load-per-call. A class makes the reuse explicit. |
| Dict output from chunker (not Pydantic) | Pydantic `DocumentChunk` model | The dict format matches the bulk-insert API expected by the DB session. Converting to Pydantic then back to dict for insertion is unnecessary indirection. |

---

## 6. Test Results

All three components verified:

```
Seed data: 12 documents, 2252 total words, 12 unique categories
  Average length: 187 words/doc
  All metadata fields present (category, author, version)

Chunker: Splits correctly at paragraph/sentence boundaries
  500x "test document" → 4 chunks (830, 831, 831, 13 words)
  12 seed docs → 12 chunks (each doc < 1000 tokens, no splitting needed)

Embedding service: Model downloaded and cached
  Single embedding: 384 dims, values in [-0.04, 0.06] range
  Batch embedding: 2 vectors of 384 dims
  Model cached at ~/.cache/huggingface for subsequent runs
```

The documents are short enough that each produces a single chunk (under 1000 tokens each). For more interesting chunking in the demo, the documents could be expanded, but functionally the pipeline is correct — it handles larger documents properly as verified by the 500-sentence test.

---

## 7. What's Next

- [ ] Sub-chunk 2.3: Seed script + ingestion flow — `scripts/seed_documents.py` + `POST /documents` endpoint
- [ ] Sub-chunk 2.4: Hybrid search — pgvector `<=>` + tsvector weighted fusion
- [ ] Sub-chunk 2.5: Query rewriting + multi-query — LLM few-shot rewriting, variant generation
- [ ] Sub-chunk 2.6: Reranker — cross-encoder reranking
- [ ] Sub-chunk 2.7: Integration + demo — full pipeline test

---

## 8. Gotchas & Lessons

- **sentence-transformers downloads on first use.** The `SentenceTransformer('all-MiniLM-L6-v2')` call triggers a ~22MB download from Hugging Face Hub on the first run. Subsequent runs use a local cache. If deploying in an air-gapped environment, you'd need to pre-download the model.
- **The venv needed `--system-site-packages`** because PyTorch was installed system-wide (Arch Linux package) but not in the venv. Without it, `sentence-transformers` would hang indefinitely trying to install PyTorch from pip (2GB download). Using the system torch with `--system-site-packages` is faster and avoids the duplicate.
- **Seed documents are ~187 words each** — well under the 1000-token chunk size. They won't demonstrate multi-chunk retrieval unless expanded. The chunker itself handles multi-chunk correctly (verified with a 500-sentence test document that produced 4 chunks), but the demo data is too short to show it. If multi-chunk retrieval is important for the demo, the documents should be 3-5x longer.
- **Chunk overlap was verified in the output** — consecutive chunks share ~200 tokens of context at their boundaries. This was confirmed by checking overlapping text between chunks 0 and 1 in the test.
