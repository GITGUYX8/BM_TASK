# ingest.py is an orchestrator (a coordinator that calls other pieces in sequence)
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from app.rag.chunker import chunk_document
from app.rag.embedding import EmbeddingService
from app.db.models import DocumentChunk

_embedder = None

def _get_embedder() -> EmbeddingService:
    global _embedder
    if _embedder is None:
        _embedder = EmbeddingService()
    return _embedder


async def ingest_document(
    session: AsyncSession,
    title: str,
    content: str,
    metadata: dict | None = None,
) -> tuple[uuid.UUID, int]:
    embedder = _get_embedder()
    chunks = chunk_document(title, content, metadata)
    chunk_texts = [c["chunk_text"] for c in chunks]
    embeddings = embedder.embed_batch(chunk_texts)
    doc_id = uuid.uuid4()
    for chunk, embedding in zip(chunks, embeddings):
        db_chunk = DocumentChunk(
            id=uuid.uuid4(),
            title=chunk["title"],
            content=chunk["content"],
            chunk_index=chunk["chunk_index"],
            chunk_text=chunk["chunk_text"],
            embedding=embedding,
            doc_metadata=chunk["metadata"],
        )
        session.add(db_chunk)
    await session.commit()
    return doc_id, len(chunks)
