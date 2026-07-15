from fastapi import APIRouter

router = APIRouter()


@router.post("/documents")
async def create_document():
    return {"document_id": "", "chunks_count": 0, "status": "indexed"}
