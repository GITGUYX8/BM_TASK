from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None, status_code: int = 400):
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code


ERROR_CATALOG = {
    "ORDER_NOT_FOUND": (404, "Order with the given ID was not found"),
    "ORDER_PROCESSING": (409, "Order is currently processing"),
    "VALIDATION_ERROR": (422, "Invalid request data"),
    "IDEMPOTENCY_MISMATCH": (409, "Body mismatch for given idempotency key"),
    "LLM_API_ERROR": (502, "LLM provider returned an error"),
    "BUDGET_EXCEEDED": (402, "Cost ceiling exceeded"),
    "RATE_LIMITED": (429, "Too many requests"),
    "INTERNAL_ERROR": (500, "Unexpected internal error"),
    "DOCUMENT_NOT_FOUND": (404, "Document with the given ID was not found"),
}


def register_error_handlers(app: FastAPI):
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred",
                    "details": {},
                }
            },
        )
