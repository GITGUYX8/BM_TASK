import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import DocumentCreate, DocumentResponse
from app.db.session import get_session
from app.rag.ingest import ingest_document

router = APIRouter()


@router.post("/documents", response_model=DocumentResponse, status_code=201)
async def create_document(
    body: DocumentCreate,
    session: AsyncSession = Depends(get_session),
):
    doc_id, chunks_count = await ingest_document(
        session, body.title, body.content, body.metadata
    )
    return DocumentResponse(
        document_id=doc_id,
        chunks_count=chunks_count,
        status="indexed",
    )
