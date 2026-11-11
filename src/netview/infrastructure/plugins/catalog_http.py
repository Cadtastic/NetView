"""Fetch the plugin catalog over HTTP, and read the copy bundled with the package."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from importlib import resources
from typing import Any

from netview import __version__
from netview.application.plugins.plugin_json import PluginIndex, parse_index
from netview.domain.errors import CatalogUnavailableError, ValidationError


class HttpCatalogFetcher:
    def __init__(
        self,
        url: str,
        timeout_s: float = 10.0,
        max_bytes: int = 1_000_000,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.source = url
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._opener = opener

    def fetch(self) -> PluginIndex:
        request = urllib.request.Request(self.source, headers={"User-Agent": f"netview/{__version__}"})
        try:
            with self._opener(request, timeout=self._timeout_s) as response:
                body: bytes = response.read(self._max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise CatalogUnavailableError(f"Couldn't read the plugin list ({exc.code})") from exc
        except (urllib.error.URLError, OSError) as exc:  # includes timeouts
            raise CatalogUnavailableError("Couldn't reach GitHub") from exc
        if len(body) > self._max_bytes:
            raise CatalogUnavailableError("Couldn't read the plugin list (too large)")
        try:
            return parse_index(json.loads(body.decode("utf-8-sig")))
        except (ValueError, ValidationError) as exc:
            raise CatalogUnavailableError(f"Couldn't read the plugin list ({exc})") from exc


def bundled_index() -> PluginIndex:
    text = resources.files("netview.infrastructure.plugins").joinpath("catalog.json").read_text("utf-8")
    return parse_index(json.loads(text))
