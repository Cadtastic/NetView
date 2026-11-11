"""GSM7248 API. Plain ``def`` routes: the SNMP client blocks."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from .console import ConsoleError
from .service import Gsm7248Service


def build_router(service: Gsm7248Service) -> APIRouter:
    router = APIRouter()

    @router.get("/summary")
    def summary() -> dict[str, Any]:
        return service.summary()

    @router.get("/ports")
    def ports() -> list[dict[str, Any]]:
        return service.ports()

    # Port names contain a slash (0/5) and servers decode %2F before routing, so the name is a path
    # parameter; the samples route comes first because a path parameter would swallow "/samples".
    @router.get("/ports/{name:path}/samples")
    def samples(
        name: str,
        from_ms: int | None = None,
        to_ms: int | None = None,
        resolution: Annotated[str, Query(pattern="^(raw|5m)$")] = "raw",
    ) -> list[dict[str, Any]]:
        if not service.has_port(name):
            raise HTTPException(status_code=404, detail=f"unknown port {name!r}")
        return service.samples(name, from_ms, to_ms, resolution)

    @router.get("/ports/{name:path}")
    def port(name: str) -> dict[str, Any]:
        found = service.port(name)
        if found is None:
            raise HTTPException(status_code=404, detail=f"unknown port {name!r}")
        return found

    @router.get("/macs")
    def macs() -> list[dict[str, Any]]:
        return service.macs()

    @router.get("/vlans")
    def vlans() -> list[dict[str, Any]]:
        return service.vlans()

    @router.post("/poll", status_code=202)
    def poll() -> Any:
        if not service.start_poll_all():
            return JSONResponse({"detail": "poll already running"}, status_code=409)
        return {"started": True}

    @router.post("/test")
    def test(body: dict[str, Any] | None = None) -> dict[str, str]:
        # the stored settings are used: the client never sends (or gets back) a secret
        target = service.settings.target()
        if target is None:
            return {"ok": "false", "error": "not configured"}
        return service.test_connection(target)

    # The console routes read no request body: the commands come from the stored, pattern-checked settings.
    @router.get("/console")
    def console() -> dict[str, Any]:
        return service.console()

    @router.post("/console/probe")
    def console_probe() -> Any:
        try:
            result = service.probe_console()
        except ConsoleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result is None:
            return JSONResponse({"detail": "probe already running"}, status_code=409)
        return result

    @router.post("/console/open", status_code=202)
    def console_open() -> dict[str, bool]:
        try:
            service.open_console()
        except ConsoleError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"opened": True}

    return router
