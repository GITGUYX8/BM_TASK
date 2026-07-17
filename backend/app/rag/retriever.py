import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import RetrievedChunk


def _query_to_tsquery(query: str) -> str:
    """
    Convert plain text into a PostgreSQL tsquery string (words joined with OR).

    Strips short words (<3 chars) since they're usually stopwords that add noise.
    If nothing remains, returns empty string — caller should bail early.
    """
    words = re.findall(r"\w+", query.lower())
    words = [w for w in words if len(w) > 2]
    if not words:
        return ""
    return " | ".join(words)


async def hybrid_search(
    session: AsyncSession,
    query_embedding: list[float],
    query_text: str,
    top_k: int = 10,
    vector_weight: float = 0.7,
) -> list[RetrievedChunk]:
    """
    Run hybrid search combining pgvector cosine similarity + PostgreSQL full-text search.

    Args:
        session: async DB session
        query_embedding: 384-dim embedding vector for the query text
        query_text: original query text (for tsquery generation)
        top_k: max results to return
        vector_weight: weight for vector score (0-1); keyword gets (1 - vector_weight)

    Returns:
        List of RetrievedChunk objects ranked by fused score descending
    """
    tsquery_str = _query_to_tsquery(query_text)
    if not tsquery_str:
        return []

    # ── Layer 1: Bi-encoder (semantic, whole corpus) ──
    #   d.embedding <=> :query_embedding  → cosine similarity (SentenceTransformer)
    # ── Layer 2: FTS (exact keyword, whole corpus) ──
    #   to_tsvector(chunk_text) @@ to_tsquery  → term matching (PostgreSQL built-in)
    # Fused score: vector * 0.7 + keyword * 0.3
    # Layer 3 (cross-encoder reranker) runs after this, on top ~10 candidates only.
    sql = text(
        """
        SELECT
            d.title,
            d.chunk_text,
            d.doc_metadata,
            1 - (d.embedding <=> :query_embedding) AS vector_score,
            COALESCE(ts_rank(to_tsvector('english', d.chunk_text), to_tsquery(:tsquery)), 0) AS keyword_score
        FROM documents d
        WHERE 1 - (d.embedding <=> :query_embedding) > :threshold
           OR to_tsvector('english', d.chunk_text) @@ to_tsquery(:tsquery)
        ORDER BY
            (1 - (d.embedding <=> :query_embedding)) * :vector_weight +
            COALESCE(ts_rank(to_tsvector('english', d.chunk_text), to_tsquery(:tsquery)), 0) * :keyword_weight DESC
        LIMIT :top_k
        """
    )

    result = await session.execute(
        sql,
        {
            "query_embedding": query_embedding,
            "tsquery": tsquery_str,
            "threshold": 0.7,
            "vector_weight": vector_weight,
            "keyword_weight": 1 - vector_weight,
            "top_k": top_k,
        },
    )

    rows = result.fetchall()
    # Convert raw DB rows into typed Pydantic models so downstream agents
    # get validated data with named fields instead of magic dict keys
    return [
        RetrievedChunk(
            document_title=row.title,
            chunk_text=row.chunk_text,
            vector_score=float(row.vector_score) if row.vector_score else 0.0,
            keyword_score=float(row.keyword_score) if row.keyword_score else 0.0,
            fused_score=(
                float(row.vector_score) * vector_weight
                + float(row.keyword_score) * (1 - vector_weight)
            )
            if row.vector_score
            else float(row.keyword_score) * (1 - vector_weight),
            metadata=row.doc_metadata or {},
        )
        for row in rows
    ]
