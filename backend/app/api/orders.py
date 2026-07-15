from fastapi import APIRouter

router = APIRouter()


@router.get("/orders")
async def list_orders():
    return {"orders": []}


@router.post("/orders")
async def create_order():
    return {"order_id": "", "status": "queued"}


@router.get("/orders/{order_id}")
async def get_order(order_id: str):
    return {"order_id": order_id, "status": "unknown"}


@router.get("/orders/{order_id}/stream")
async def stream_order(order_id: str):
    pass
