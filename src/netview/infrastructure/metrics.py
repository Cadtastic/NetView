"""Ring-buffer metrics store."""

import threading
from collections import deque


class RingMetricsStore:
    def __init__(self, maxlen: int = 120) -> None:
        self._maxlen = maxlen
        self._lock = threading.Lock()
        self._data: dict[str, deque[tuple[int, float | None]]] = {}

    def append(self, series: str, t_ms: int, value: float | None) -> None:
        with self._lock:
            buf = self._data.get(series)
            if buf is None:
                buf = self._data[series] = deque(maxlen=self._maxlen)
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
