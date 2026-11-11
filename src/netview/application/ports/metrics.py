"""Metrics store port."""

from collections.abc import Sequence
from typing import Protocol


class MetricsStore(Protocol):
    def append(self, series: str, t_ms: int, value: float | None) -> None: ...
    def series(self, name: str, limit: int = 120) -> list[tuple[int, float | None]]: ...
    def names(self, prefix: str = "") -> list[str]: ...
    def snapshot(
        self, prefixes: Sequence[str] = (), since_ms: int = 0
    ) -> dict[str, list[tuple[int, float | None]]]:
        """Points with ``t > since_ms`` of every series starting with one of ``prefixes`` (all if empty)."""
        ...

    def drop(self, name: str) -> None:
        """Forget a series. Unknown names are ignored."""
        ...
