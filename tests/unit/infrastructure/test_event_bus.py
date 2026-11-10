import asyncio

from netview.domain.events import DomainEvent, EventKind
from netview.infrastructure.event_bus import InMemoryEventBus


def _ev(text: str) -> DomainEvent:
    return DomainEvent(EventKind.NEW, text, 1)


def test_bus_handler_exception_isolated() -> None:
    bus = InMemoryEventBus()
    seen: list[str] = []

    def bad(e: DomainEvent) -> None:
        raise RuntimeError("nope")

    bus.subscribe(bad)
    bus.subscribe(lambda e: seen.append(e.text))
    bus.publish(_ev("a"))
    assert seen == ["a"]


def test_unsubscribe() -> None:
    bus = InMemoryEventBus()
    seen: list[str] = []
    off = bus.subscribe(lambda e: seen.append(e.text))
    bus.publish(_ev("a"))
    off()
    bus.publish(_ev("b"))
    assert seen == ["a"]


def test_stream_receives_events_published_from_a_thread() -> None:
    async def scenario() -> list[str]:
        bus = InMemoryEventBus()
        got: list[str] = []

        async def consume() -> None:
            async for e in bus.stream():
                got.append(e.text)
                if len(got) == 2:
                    return

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.05)
        await asyncio.to_thread(lambda: (bus.publish(_ev("x")), bus.publish(_ev("y"))))
        await asyncio.wait_for(task, 2)
        return got

    assert asyncio.run(scenario()) == ["x", "y"]


def test_stream_full_queue_drops_oldest() -> None:
    async def scenario() -> tuple[int, str]:
        bus = InMemoryEventBus()
        agen = bus.stream()
        first = asyncio.create_task(agen.__anext__())
        await asyncio.sleep(0.05)  # subscriber registered
        for i in range(1005):
            bus.publish(_ev(str(i)))
        await asyncio.sleep(0.1)
        got = [(await first).text]
        while len(got) < 1000:
            got.append((await agen.__anext__()).text)
        await agen.aclose()
        return len(got), got[-1]

    n, last = asyncio.run(scenario())
    assert n == 1000
    assert last == "1004"
