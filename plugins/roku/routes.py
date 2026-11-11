"""Roku API. Plain ``def`` routes: ECP calls block."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Response
from fastapi.responses import JSONResponse

from .service import CommandError, DocumentError, RokuService, UnknownTv

_STATIC = Path(__file__).parent / "static"
_SCRIPTS = frozenset({"find_rokus.py", "find_rokus.ps1"})
_ICON_TTL_S = 3600.0
_ICON_MAX = 256
_ICON_MAX_BYTES = 65536
# The host's SecurityMiddleware sets the Content-Security-Policy on every response, this one included.
_ICON_HEADERS = {"X-Content-Type-Options": "nosniff"}


def _icon_type(data: bytes, claimed: str) -> str | None:
    """The claimed type when the bytes really are that raster format, else None.

    The TV's answer is served from netview's own origin, so nothing scriptable (SVG, HTML) gets through.
    """
    if claimed == "image/png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return claimed
    if claimed == "image/jpeg" and data.startswith(b"\xff\xd8\xff"):
        return claimed
    if claimed == "image/gif" and data[:6] in (b"GIF87a", b"GIF89a"):
        return claimed
    if claimed == "image/webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return claimed
    return None


_Body = Annotated[dict[str, Any], Body()]


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _guarded(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except UnknownTv:
        return _error(404, "Unknown TV")
    except CommandError as err:
        return _error(err.status_code, err.message)
    except DocumentError as err:
        return _error(422, err.message)
    except ValueError as err:
        return _error(422, str(err))


class _IconCache:
    """Icons rarely change, so the TV is asked once an hour per app."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], tuple[float, bytes, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> tuple[bytes, str] | None:
        with self._lock:
            hit = self._items.get(key)
            if hit is None or time.monotonic() - hit[0] > _ICON_TTL_S:
                return None
            return hit[1], hit[2]

    def put(self, key: tuple[str, str], data: bytes, content_type: str) -> None:
        with self._lock:
            if len(self._items) >= _ICON_MAX:
                self._items.pop(next(iter(self._items)))
            self._items[key] = (time.monotonic(), data, content_type)


def build_router(service: RokuService) -> APIRouter:
    router = APIRouter()
    icons = _IconCache()

    @router.get("/tvs")
    def tvs() -> dict[str, Any]:
        return service.list_tvs()

    @router.get("/tvs/document")
    def document() -> dict[str, Any]:
        return service.document()

    @router.put("/tvs/document")
    def put_document(body: _Body) -> Any:
        text = body.get("text")
        if not isinstance(text, str):
            return _error(422, "text must be a string")
        return _guarded(lambda: service.save_document(text))

    @router.post("/scan", status_code=202)
    def start_scan() -> Any:
        if not service.start_scan():
            return _error(409, "scan already running")
        return {"started": True}

    @router.get("/scan")
    def scan_state() -> dict[str, Any]:
        return service.scan_state()

    @router.post("/tvs/{tv_id}/key/{key}")
    def press(
        tv_id: str, key: str, action: Annotated[str, Query(pattern="^(press|down|up)$")] = "press"
    ) -> Any:
        def run() -> dict[str, bool]:
            service.send_key(tv_id, key, action)
            return {"ok": True}

        return _guarded(run)

    @router.post("/tvs/{tv_id}/launch/{app}")
    def launch(tv_id: str, app: str) -> Any:
        def run() -> dict[str, bool]:
            service.launch(tv_id, app)
            return {"ok": True}

        return _guarded(run)

    @router.post("/tvs/{tv_id}/text")
    def text(tv_id: str, body: _Body) -> Any:
        value = body.get("text")
        if not isinstance(value, str):
            return _error(422, "text must be a string")

        def run() -> dict[str, bool]:
            service.type_text(tv_id, value)
            return {"ok": True}

        return _guarded(run)

    @router.post("/tvs/{tv_id}/refresh", status_code=202)
    def refresh(tv_id: str) -> Any:
        def run() -> dict[str, bool]:
            service.refresh(tv_id)
            return {"ok": True}

        return _guarded(run)

    @router.get("/tvs/{tv_id}/icon/{app}")
    def icon(tv_id: str, app: str) -> Any:
        def run() -> Response:
            cached = icons.get((tv_id, app))
            if cached is None:
                data, raw_type = service.icon(tv_id, app)
                content_type = raw_type.split(";", 1)[0].strip().lower()
                verified = _icon_type(data, content_type)
                if verified is None or len(data) > _ICON_MAX_BYTES:
                    return _error(502, "The TV sent something that isn't a usable icon")
                cached = (data, verified)
                icons.put((tv_id, app), *cached)
            data, content_type = cached
            return Response(data, media_type=content_type, headers=_ICON_HEADERS)

        return _guarded(run)

    @router.get("/scripts/{name}")
    def script(name: str) -> Any:
        path = _STATIC / name
        if name not in _SCRIPTS or not path.is_file():
            return _error(404, "No such script")
        return Response(path.read_bytes(), media_type="text/plain; charset=utf-8")

    return router
