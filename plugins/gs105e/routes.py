"""GS105E API. Plain ``def`` routes: the switch client blocks."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from .service import Gs105eService

_PORT_COUNT = 5


def _check_port(n: int) -> None:
    if not 1 <= n <= _PORT_COUNT:
        raise HTTPException(status_code=404, detail=f"unknown port {n}")


def build_router(service: Gs105eService) -> APIRouter:
    router = APIRouter()

    @router.get("/summary")
    def summary() -> dict[str, Any]:
        return service.summary()

    @router.get("/ports")
    def ports() -> list[dict[str, Any]]:
        return service.ports()

    @router.get("/config")
    def config() -> dict[str, Any]:
        return service.config()

    # declared before /ports/{n}
    @router.get("/ports/{n}/samples")
    def samples(
        n: int,
        from_ms: int | None = None,
        to_ms: int | None = None,
        resolution: Annotated[str, Query(pattern="^(raw|5m)$")] = "raw",
    ) -> list[dict[str, Any]]:
        _check_port(n)
        return service.samples(n, from_ms, to_ms, resolution)

    @router.get("/ports/{n}")
    def port(n: int) -> dict[str, Any]:
        _check_port(n)
        found = service.port(n)
        if found is None:
            raise HTTPException(status_code=503, detail=f"no data for port {n} yet")
        return found

    @router.post("/poll", status_code=202)
    def poll() -> Any:
        reason = service.poll_block_reason()
        if reason is not None:
            return JSONResponse({"detail": reason}, status_code=409)
        if not service.start_poll_all():
            return JSONResponse({"detail": "poll already running"}, status_code=409)
        return {"started": True}

    @router.post("/pause")
    def pause() -> dict[str, Any]:
        service.pause()
        return {"paused_until_ms": service.summary()["paused_until_ms"]}

    @router.delete("/pause")
    def resume() -> dict[str, Any]:
        service.resume()
        return {"paused_until_ms": None}

    @router.post("/test")
    def test(body: dict[str, Any] | None = None) -> dict[str, str]:
        # the stored settings are used: the client never sends (or gets back) a secret
        return service.test_connection()

    return router
