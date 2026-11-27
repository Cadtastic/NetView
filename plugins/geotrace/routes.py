"""GeoTrace API. Plain ``def`` routes (the store and the geocoder block).

The core guards every route: GET needs the plugin's view permission and the rest need use.
Errors are ``{"error": message}`` with 404 (unknown id), 422 (bad input), 502 (address search down) or
503 (shutting down); a traceback is never sent.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Query, Response
from fastapi.responses import FileResponse, JSONResponse

from .bundle import content_type
from .compare import differs, pairs, split_after
from .geocode import GeocodeError, Geocoder
from .model import Target
from .schemas import (
    hop_json,
    live_json,
    new_target,
    target_changes,
    target_json,
    trace_json,
    trace_once,
    trace_summary,
)
from .service import GeoTraceService, TargetLimitError
from .tiles import TileBusyError, sources
from .trends import BUCKETS, bucket

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
RANGES = {"24h": DAY_MS, "7d": 7 * DAY_MS, "30d": 30 * DAY_MS, "90d": 90 * DAY_MS}
PAGE_MAX = 200
QUERY_MAX = 200
NOT_INSTALLED = "traceroute is not installed"
SHUTTING_DOWN = "GeoTrace is shutting down"

TILE_HEADERS = {"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"}
CESIUM_HEADERS = {
    "Cache-Control": "public, max-age=31536000, immutable",
    "X-Content-Type-Options": "nosniff",
}
TILE_DIGITS = 8  # x and y stay under 2**19 (six digits); anything longer is not a tile

_Body = Annotated[Any, Body()]


def _coordinate(text: str, digits: int) -> int | None:
    """A plain non-negative decimal without a sign, a leading zero or an extension, else None."""
    if not (text.isascii() and text.isdigit()) or len(text) > digits or (len(text) > 1 and text[0] == "0"):
        return None
    return int(text)


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _duration(ms: int) -> str:
    minutes = max(ms, 0) // 60_000
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    return f"{hours} h" if hours < 48 else f"{hours // 24} days"


def route_note(age: tuple[int, int, bool] | None, now_ms: int) -> str:
    """``route changed 3 h ago`` or ``steady 2 days``, else an empty string.

    ``age`` is ``TraceStore.route_age``: how long the newest signature has held. When an earlier trace had a
    different signature, the note says how long ago the current one first appeared. Otherwise it says how
    long the route has stayed the same, but only once at least two traces agree.
    """
    if age is None:
        return ""
    since_ms, newest_ms, changed = age
    if changed:
        return f"route changed {_duration(now_ms - since_ms)} ago"
    if since_ms < newest_ms:
        return f"steady {_duration(now_ms - since_ms)}"
    return ""


def build_router(service: GeoTraceService, ctx: Any, geocoder: Geocoder) -> APIRouter:
    router = APIRouter()
    targets, traces = service.targets, service.traces

    def unknown_target(target_id: int) -> Target | JSONResponse:
        found = targets.get(target_id)
        return found if found is not None else _error(404, "unknown target")

    def started(call: Any) -> Any:
        try:
            return JSONResponse({"trace_id": call()}, status_code=202)
        except LookupError:
            return _error(404, "unknown target")
        except RuntimeError as error:
            if str(error) != SHUTTING_DOWN:
                raise
            return _error(503, SHUTTING_DOWN)

    # -- targets ---------------------------------------------------------------------------------

    @router.get("/targets")
    def list_targets() -> list[dict[str, Any]]:
        now = ctx.clock.now_ms()
        out = []
        for target in targets.list():
            last = traces.latest(target.id, 1, status=None)
            out.append(
                target_json(target, last[0] if last else None, route_note(traces.route_age(target.id), now))
            )
        return out

    @router.post("/targets", status_code=201)
    def add_target(body: _Body = None) -> Any:
        try:
            fields = new_target(body, service.settings.default_family, service.settings.default_interval_min)
            target = service.add_target(**fields)
        except (ValueError, TargetLimitError) as error:
            return _error(422, str(error))
        ctx.audit("geotrace.target.add", target=target.address)
        return JSONResponse(target_json(target), status_code=201)

    @router.put("/targets/{target_id}")
    def edit_target(target_id: int, body: _Body = None) -> Any:
        current = unknown_target(target_id)
        if isinstance(current, JSONResponse):
            return current
        try:
            changes = target_changes(body, current)
            target = service.update_target(target_id, **changes)
        except ValueError as error:
            return _error(422, str(error))
        if target is None:
            return _error(404, "unknown target")
        ctx.audit("geotrace.target.edit", target=target.address)
        return target_json(target)

    @router.delete("/targets/{target_id}")
    def delete_target(target_id: int) -> Response:
        current = targets.get(target_id)
        if current is None or not service.remove_target(target_id):
            return _error(404, "unknown target")
        ctx.audit("geotrace.target.delete", target=current.address)
        return Response(status_code=204)

    @router.post("/targets/{target_id}/trace")
    def trace_target(target_id: int) -> Any:
        return started(lambda: service.trace_now(target_id))

    @router.post("/trace-once")
    def start_trace_once(body: _Body = None) -> Any:
        try:
            address, family, mode = trace_once(body, service.settings.default_family)
        except ValueError as error:
            return _error(422, str(error))
        response = started(lambda: service.trace_once(address, family, mode))
        if response.status_code == 202:
            ctx.audit("geotrace.trace_once", target=address)
        return response

    # -- traces ----------------------------------------------------------------------------------

    @router.get("/traces/{trace_id}")
    def get_trace(trace_id: int) -> Any:
        """A saved trace, or while it runs (or if saving it failed) what the live trace shows.

        Provisional ids are negative and become a saved id once the run is stored; 0 means "not stored" and
        is never looked up.
        """
        saved_id = trace_id if trace_id > 0 else service.resolve_id(trace_id) if trace_id < 0 else None
        if saved_id is not None:
            saved = traces.get(saved_id)
            if saved is not None:
                return trace_json(saved)
        live = service.live(trace_id) if trace_id < 0 else None
        if live is None:
            return _error(404, "unknown trace")
        snap = live.snapshot()
        return live_json(
            snap.id,
            snap.status,
            snap.error,
            snap.started_ms,
            snap.hops,
            live.target_id,
            live.mode,
            live.trigger,
        )

    @router.get("/targets/{target_id}/traces")
    def list_traces(
        target_id: int, before_ms: Annotated[int | None, Query()] = None, limit: Annotated[int, Query()] = 50
    ) -> Any:
        missing = unknown_target(target_id)
        if isinstance(missing, JSONResponse):
            return missing
        return [trace_summary(t) for t in traces.page(target_id, before_ms, min(max(limit, 1), PAGE_MAX))]

    @router.get("/targets/{target_id}/compare")
    def compare(
        target_id: int, a: Annotated[int | None, Query()] = None, b: Annotated[int | None, Query()] = None
    ) -> Any:
        missing = unknown_target(target_id)
        if isinstance(missing, JSONResponse):
            return missing
        if a is not None:
            first = traces.get(a)
        else:
            # Prefer a trace that has a route; with no location data fall back to the newest done one.
            first = traces.other_route(target_id, None, 0) or next(iter(traces.latest(target_id, 1)), None)
        if first is None or first.target_id != target_id:
            return _error(404, "not enough traces to compare")
        if b is None:
            # The newest trace whose route differs; if the route never changed, the previous one.
            second = (
                traces.other_route(target_id, first.signature, first.id)
                or traces.other_route(target_id, None, first.id)
                or next((t for t in traces.latest(target_id, 2) if t.id != first.id), None)
            )
        else:
            second = traces.get(b)
        if second is None or second.target_id != target_id:
            return _error(404, "not enough traces to compare")
        rows = [
            {
                "n": n,
                "a": None if ha is None else hop_json(ha),
                "b": None if hb is None else hop_json(hb),
                "differs": differs(ha, hb),
            }
            for n, ha, hb in pairs(first.hops, second.hops)
        ]
        return {
            "a": trace_summary(first),
            "b": trace_summary(second),
            "rows": rows,
            "split_after": split_after(first, second),
        }

    @router.get("/targets/{target_id}/trends")
    def trends(target_id: int, range: Annotated[str, Query()] = "24h") -> Any:
        missing = unknown_target(target_id)
        if isinstance(missing, JSONResponse):
            return missing
        if range not in RANGES:
            return _error(422, "range must be 24h, 7d, 30d or 90d")
        now = ctx.clock.now_ms()
        return bucket(traces.between(target_id, now - RANGES[range], now), now - RANGES[range], now, BUCKETS)

    # -- tiles -----------------------------------------------------------------------------------

    @router.get("/tiles/{source}/{z}/{x}/{y}")
    def tile(source: str, z: str, x: str, y: str) -> Any:
        found = sources(service.settings).get(source)
        zoom, col, row = _coordinate(z, 2), _coordinate(x, TILE_DIGITS), _coordinate(y, TILE_DIGITS)
        if found is None or zoom is None or col is None or row is None:
            return _error(404, "no such tile")
        if zoom > found.max_zoom or col >= 2**zoom or row >= 2**zoom:
            return _error(404, "no such tile")
        try:
            result = service.tile_cache().get(found, zoom, col, row)
        except TileBusyError:
            return _error(503, "map tiles are busy")
        if result is None:
            return _error(502, "the tile server did not give a usable tile")
        return Response(result[0], media_type=result[1], headers=TILE_HEADERS)

    # -- the Cesium bundle -----------------------------------------------------------------------

    @router.get("/cesium/{version}/{path:path}")
    def cesium(version: str, path: str) -> Any:
        """Files live under their version in the URL so that ``immutable`` caching stays correct."""
        found = service.bundle.path_for(path) if version == service.bundle.version else None
        if found is None:
            return _error(404, "no such file")
        return FileResponse(found, media_type=content_type(found), headers=CESIUM_HEADERS)

    @router.post("/bundle/download", status_code=202, dependencies=[ctx.require("configure")])
    def bundle_download() -> Any:
        service.bundle.ensure_async()
        return JSONResponse(service.bundle.status(), status_code=202)

    @router.post("/geodata/update", status_code=202, dependencies=[ctx.require("configure")])
    def geodata_update() -> Any:
        service.update_geo_async(force=True)
        ctx.audit("geotrace.geodata.update")
        return JSONResponse(
            {"geo": {**service.geo.status(), "auto_update": service.settings.geo_auto_update}},
            status_code=202,
        )

    # -- status and address search ---------------------------------------------------------------

    @router.get("/status")
    def status() -> dict[str, Any]:
        service.ensure_geo_once()
        newest = traces.newest()
        tile_error = service.tile_cache().last_error()
        bundle = service.bundle.status()
        if bundle["state"] == "missing":
            service.bundle.ensure_async()
            bundle = service.bundle.status()
        return {
            "geo": {**service.geo.status(), "auto_update": service.settings.geo_auto_update},
            "tiles": {
                "last_error": tile_error[0] if tile_error else None,
                "last_error_ms": tile_error[1] if tile_error else None,
            },
            "bundle": bundle,
            # Only the choices, never the custom tile address: the page needs to know which layers to draw.
            "map": {
                "tile_source": service.settings.tile_source,
                "base_imagery": service.settings.base_imagery,
            },
            # What the Add target form and Trace once start from (Settings > General). No secrets.
            "defaults": {
                "interval_min": service.settings.default_interval_min,
                "family": service.settings.default_family,
            },
            "home_set": service.home() is not None,
            "traceroute_ok": not (newest is not None and newest.error == NOT_INSTALLED),
        }

    @router.get("/geocode", dependencies=[ctx.require("configure")])
    def geocode(q: Annotated[str, Query()] = "") -> Any:
        if not q.strip():
            return _error(422, "q is required")
        if len(q) > QUERY_MAX:
            return _error(422, f"q must be at most {QUERY_MAX} characters")
        try:
            return geocoder.search(q)
        except GeocodeError:
            return _error(502, "address search is unavailable")

    return router
