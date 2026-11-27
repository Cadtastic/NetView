"""Address search through Nominatim: one request a second at most, answers kept for an hour."""

from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

USER_AGENT = "NetView-GeoTrace/0.1.0 (+https://github.com/Cadtastic/NetView)"
URL = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&q="
MIN_GAP_S = 1.0
CACHE_TTL_S = 3600.0
CACHE_MAX = 200
TIMEOUT_S = 8.0
MAX_BYTES = 262_144

Opener = Callable[..., Any]


class GeocodeError(Exception):
    """Nominatim could not be reached or gave an answer that makes no sense."""


def default_opener(request: urllib.request.Request, timeout: float = TIMEOUT_S) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


class Geocoder:
    def __init__(
        self,
        opener: Opener = default_opener,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._opener = opener
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_request: float | None = None
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    def search(self, query: str) -> list[dict[str, Any]]:
        """``[{label, lat, lon}]``. Raises ``GeocodeError``. Blocks (waits its turn, then asks)."""
        text = query.strip()
        key = text.lower()
        hit = self._cached(key)
        if hit is not None:
            return hit
        with self._lock:
            hit = self._cached(key)  # another caller may have asked the same while this one waited
            if hit is not None:
                return hit
            if self._last_request is not None:
                wait = MIN_GAP_S - (self._monotonic() - self._last_request)
                if wait > 0:
                    self._sleep(wait)
            self._last_request = self._monotonic()
            results = self._ask(text)
            self._store(key, results)
            return list(results)

    def _cached(self, key: str) -> list[dict[str, Any]] | None:
        found = self._cache.get(key)
        if found is None or self._monotonic() - found[0] > CACHE_TTL_S:
            return None
        return list(found[1])

    def _store(self, key: str, results: list[dict[str, Any]]) -> None:
        self._cache.pop(key, None)
        while len(self._cache) >= CACHE_MAX:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (self._monotonic(), results)

    def _ask(self, text: str) -> list[dict[str, Any]]:
        request = urllib.request.Request(
            URL + urllib.parse.quote(text, safe=""),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        try:
            response = self._opener(request, timeout=TIMEOUT_S)
            try:
                raw = response.read(MAX_BYTES + 1)
            finally:
                close = getattr(response, "close", None)
                if close is not None:
                    close()
            if len(raw) > MAX_BYTES:
                raise ValueError("answer too large")
            data = json.loads(raw)
        except (OSError, ValueError) as error:  # urllib's errors are OSErrors; JSON's are ValueErrors
            raise GeocodeError(str(error)) from error
        if not isinstance(data, list):
            raise GeocodeError("unexpected answer")
        out: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                out.append(
                    {
                        "label": str(item["display_name"]),
                        "lat": float(item["lat"]),
                        "lon": float(item["lon"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out
