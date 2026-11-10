"""Map domain errors to HTTP responses."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from netview.domain.errors import (
    CapabilityUnavailableError,
    NoNetworkError,
    NotFoundError,
    ScanInProgressError,
    ValidationError,
)


def _handler(status: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handle(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=status)

    return handle


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, _handler(404))
    app.add_exception_handler(ValidationError, _handler(422))
    app.add_exception_handler(CapabilityUnavailableError, _handler(409))
    app.add_exception_handler(ScanInProgressError, _handler(409))
    app.add_exception_handler(NoNetworkError, _handler(503))
