from sentence_transformers import CrossEncoder

from app.core.models import RetrievedChunk

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_reranker = None


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(MODEL_NAME)
    return _reranker


# ── Layer 3: Cross-encoder (precise, top candidates only) ──
# Bi-encoder + FTS retrieve ~10 candidates; this re-ranks them by processing
# (query, chunk) as a single sequence for token-level relevance scoring.
def rerank(query: str, chunks: list[RetrievedChunk], top_k: int = 3) -> list[RetrievedChunk]:
    if not chunks or not query:
        return chunks[:top_k]

    model = _get_reranker()
    pairs = [(query, c.chunk_text) for c in chunks]
    scores = model.predict(pairs, show_progress_bar=False)

    scored = list(zip(chunks, scores))
    scored.sort(key=lambda x: x[1], reverse=True)

    results = []
    for chunk, score in scored[:top_k]:
        chunk.fused_score = float(score)
        results.append(chunk)

    return results
