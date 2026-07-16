"""Seed script: ingests demo documents into the RAG store.

Usage:
    cd backend && python -m scripts.seed_documents --count 12
"""
import asyncio
import argparse
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.seed_data import SEED_DOCUMENTS
from app.rag.ingest import ingest_document
from app.db.session import async_session


async def main():
    parser = argparse.ArgumentParser(description="Seed RAG store with demo documents")
    parser.add_argument("--count", type=int, default=12, help="Number of documents to ingest")
    args = parser.parse_args()

    docs = SEED_DOCUMENTS[: args.count]
    async with async_session() as session:
        for doc in docs:
            doc_id, chunks = await ingest_document(
                session, doc["title"], doc["content"], doc["metadata"]
            )
            print(f"  Ingested: {doc['title']} — {chunks} chunks, id={doc_id}")
        await session.commit()
    print(f"\nDone: {len(docs)} documents ingested")


if __name__ == "__main__":
    asyncio.run(main())
