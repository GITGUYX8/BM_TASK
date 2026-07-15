from app.core.models import RetrievedChunk


def rerank(query: str, chunks: list[RetrievedChunk], top_k: int = 3) -> list[RetrievedChunk]:
    return chunks[:top_k]
