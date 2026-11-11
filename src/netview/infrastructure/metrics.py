"""Ring-buffer metrics store."""

import threading
from collections import deque
from collections.abc import Sequence


class RingMetricsStore:
    """Keeps the newest ``maxlen`` points per series, or ``long_maxlen`` for names under ``long_prefixes``."""

    def __init__(
        self,
        maxlen: int = 120,
        long_prefixes: Sequence[str] = (),
        long_maxlen: int = 720,
    ) -> None:
        self._maxlen = maxlen
        self._long_prefixes = tuple(long_prefixes)
        self._long_maxlen = long_maxlen
        self._lock = threading.Lock()
        self._data: dict[str, deque[tuple[int, float | None]]] = {}

    def _capacity(self, series: str) -> int:
        return self._long_maxlen if series.startswith(self._long_prefixes) else self._maxlen

    def append(self, series: str, t_ms: int, value: float | None) -> None:
        with self._lock:
            buf = self._data.get(series)
            if buf is None:
                buf = self._data[series] = deque(maxlen=self._capacity(series))
            buf.append((t_ms, value))

    def series(self, name: str, limit: int = 120) -> list[tuple[int, float | None]]:
        with self._lock:
            buf = self._data.get(name)
            if buf is None or limit <= 0:
                return []
            return list(buf)[-limit:]

    def names(self, prefix: str = "") -> list[str]:
        with self._lock:
            return sorted(n for n in self._data if n.startswith(prefix))

    def snapshot(
        self, prefixes: Sequence[str] = (), since_ms: int = 0
    ) -> dict[str, list[tuple[int, float | None]]]:
        wanted = tuple(prefixes)
        with self._lock:
            out: dict[str, list[tuple[int, float | None]]] = {}
            for name in sorted(self._data):
                if wanted and not name.startswith(wanted):
                    continue
                fresh = [(t, v) for t, v in self._data[name] if t > since_ms]
                if fresh:
                    out[name] = fresh
            return out

    def drop(self, name: str) -> None:
        with self._lock:
            self._data.pop(name, None)
