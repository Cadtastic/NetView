"""Server-sent events: one ``domain`` event per bus event."""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import asdict

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from netview.domain.events import DomainEvent
from netview.presentation.api.deps import Services

router = APIRouter()

KEEP_ALIVE_S = 15.0
QUEUE_SIZE = 1000


def _frame(e: DomainEvent) -> str:
    payload = json.dumps(asdict(e) | {"kind": e.kind.value}, ensure_ascii=False)
    return f"event: domain\ndata: {payload}\n\n"


@router.get("/stream")
async def stream(services: Services) -> StreamingResponse:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[DomainEvent] = asyncio.Queue(maxsize=QUEUE_SIZE)

    def offer(e: DomainEvent) -> None:
        if queue.full():
            queue.get_nowait()  # drop the oldest
        queue.put_nowait(e)

    def on_event(e: DomainEvent) -> None:  # the bus may call this from any thread
        with contextlib.suppress(RuntimeError):  # the loop is closed during shutdown
            loop.call_soon_threadsafe(offer, e)

    unsubscribe = services.bus.subscribe(on_event)  # subscribed before the response starts

    async def frames() -> AsyncIterator[str]:
        try:
            yield ": connected\n\n"
            while True:
                try:
                    yield _frame(await asyncio.wait_for(queue.get(), timeout=KEEP_ALIVE_S))
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            unsubscribe()

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
