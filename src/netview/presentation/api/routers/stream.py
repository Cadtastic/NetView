"""Server-sent events: a ``domain`` frame per bus event and a coalesced ``state`` frame."""

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from netview.domain.events import DomainEvent
from netview.presentation.api.deps import SESSION_COOKIE, Services
from netview.presentation.api.permissions import require_permission

router = APIRouter()

KEEP_ALIVE_S = 15.0
QUEUE_SIZE = 1000
STATE_MIN_GAP_S = 1.0  # at most one ``state`` frame per second per stream


def _frame(e: DomainEvent) -> str:
    payload = json.dumps(asdict(e) | {"kind": e.kind.value}, ensure_ascii=False)
    return f"event: domain\ndata: {payload}\n\n"


def _state_frame() -> str:
    return f'event: state\ndata: {{"t_ms": {int(time.time() * 1000)}}}\n\n'


@router.get("/stream", dependencies=[require_permission("core.view")])
async def stream(services: Services, request: Request) -> StreamingResponse:
    # Keep the token, not the principal: a user disabled or signed out mid-stream must lose the stream.
    token = request.cookies.get(SESSION_COOKIE)
    auth = services.auth
    loop = asyncio.get_running_loop()
    # None is the "state changed" marker; anything else is a domain event
    queue: asyncio.Queue[DomainEvent | None] = asyncio.Queue(maxsize=QUEUE_SIZE)

    def offer(e: DomainEvent | None) -> None:
        if queue.full():
            queue.get_nowait()  # drop the oldest
        queue.put_nowait(e)

    def post(e: DomainEvent | None) -> None:  # the bus and notifier may call from any thread
        with contextlib.suppress(RuntimeError):  # the loop is closed during shutdown
            loop.call_soon_threadsafe(offer, e)

    # subscribed before the response starts
    unsubscribe_events = services.bus.subscribe(post)
    unsubscribe_state = services.notifier.subscribe(lambda: post(None))

    async def frames() -> AsyncIterator[str]:
        last_state = float("-inf")
        state_pending = False
        next_check = time.monotonic() + KEEP_ALIVE_S
        try:
            yield ": connected\n\n"
            while True:
                # Re-check on a clock, not on idleness: busy streams never go quiet.
                now = time.monotonic()
                if now >= next_check:
                    if auth is not None:
                        # The same rules as opening the stream: a live session, the right to view, and
                        # no password change pending. A role edit can take core.view away mid-stream.
                        principal = await run_in_threadpool(auth.sessions.resolve, token) if token else None
                        if (
                            principal is None
                            or not principal.can("core.view")
                            or principal.must_change_password
                        ):
                            return
                    next_check = time.monotonic() + KEEP_ALIVE_S
                    now = time.monotonic()
                timeout = next_check - now
                if state_pending:
                    timeout = min(timeout, max(0.0, last_state + STATE_MIN_GAP_S - now))
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=timeout)
                except TimeoutError:
                    if state_pending:
                        if time.monotonic() >= last_state + STATE_MIN_GAP_S:  # the trailing frame is due
                            state_pending = False
                            last_state = time.monotonic()
                            yield _state_frame()
                    else:
                        yield ": keep-alive\n\n"
                    continue
                if item is not None:
                    yield _frame(item)
                elif time.monotonic() - last_state >= STATE_MIN_GAP_S:
                    last_state = time.monotonic()
                    state_pending = False
                    yield _state_frame()
                else:
                    state_pending = True
        finally:
            unsubscribe_events()
            unsubscribe_state()

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
