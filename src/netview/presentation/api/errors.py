"""Map domain errors to HTTP responses."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from netview.domain.errors import (
    AuthenticationError,
    CapabilityUnavailableError,
    CatalogUnavailableError,
    ConflictError,
    InstallError,
    NoNetworkError,
    NotFoundError,
    PermissionDeniedError,
    ScanInProgressError,
    SetupRequiredError,
    TooManyAttemptsError,
    ValidationError,
)


def _handler(status: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handle(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=status)

    return handle


async def _validation(_request: Request, exc: Exception) -> JSONResponse:
    body: dict[str, object] = {"error": str(exc)}
    fields = getattr(exc, "fields", None)
    if fields:
        body["fields"] = fields  # field name -> message, for a settings form
    return JSONResponse(body, status_code=422)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, _handler(404))
    app.add_exception_handler(ValidationError, _validation)
    app.add_exception_handler(CapabilityUnavailableError, _handler(409))
    app.add_exception_handler(ScanInProgressError, _handler(409))
    app.add_exception_handler(NoNetworkError, _handler(503))
    app.add_exception_handler(ConflictError, _handler(409))
    app.add_exception_handler(InstallError, _handler(422))
    app.add_exception_handler(CatalogUnavailableError, _handler(503))
    app.add_exception_handler(AuthenticationError, _handler(401))
    app.add_exception_handler(PermissionDeniedError, _handler(403))
    app.add_exception_handler(SetupRequiredError, _handler(409))
    app.add_exception_handler(TooManyAttemptsError, _handler(429))
