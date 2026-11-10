"""Clock port."""

from typing import Protocol


class Clock(Protocol):
    def now_ms(self) -> int: ...
