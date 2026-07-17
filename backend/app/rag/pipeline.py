from collections.abc import Callable
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.embedding import EmbeddingService
from app.rag.rewriter import rewrite_query
from app.rag.multi_query import expand_queries, deduplicate_by_text
from app.rag.retriever import hybrid_search
from app.rag.reranker import rerank
from app.core.models import RetrievedChunk


async def retrieve(
    session: AsyncSession,
    description: str,
    embedder: EmbeddingService | None = None,
    llm_call: Callable | None = None,
    top_k: int = 3,
) -> list[RetrievedChunk]:
    if embedder is None:
        embedder = EmbeddingService()

    # Retrieval stack: rewrite + expand (LLM) → hybrid search (bi-encoder + FTS) → dedup → rerank (cross-encoder)
    rewritten = await rewrite_query(description, llm_call)
    variants = await expand_queries(rewritten, llm_call)

    all_chunks: list[RetrievedChunk] = []
    for variant in variants:
        query_embedding = embedder.embed(variant)
        chunks = await hybrid_search(session, query_embedding, variant, top_k=top_k * 3)
        all_chunks.extend(chunks)

    deduped = deduplicate_by_text(all_chunks, top_k=top_k * 2)
    ranked = rerank(description, deduped, top_k=top_k)
    return ranked
