from fastapi import FastAPI
from app.api.orders import router as orders_router
from app.api.documents import router as documents_router
from app.api.metrics import router as metrics_router
from app.api.errors import register_error_handlers

app = FastAPI(
    title="Work Order Processing System",
    description="Multi-agent AI pipeline for processing work orders with RAG, real-time streaming, and observability.",
    version="0.1.0",
    docs_url="/docs",
)

app.include_router(orders_router, prefix="/api", tags=["orders"])
app.include_router(documents_router, prefix="/api", tags=["documents"])
app.include_router(metrics_router, tags=["metrics"])

register_error_handlers(app)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
