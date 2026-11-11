import io
import json
import urllib.error
from typing import Any

import pytest

from netview import __version__
from netview.application.plugins.plugin_json import DEFAULT_ARCHIVE_URL, build_index, index_to_dict
from netview.domain.errors import CatalogUnavailableError
from netview.infrastructure.plugins.catalog_http import HttpCatalogFetcher, bundled_index

URL = "https://example.test/index.json"


class _Response(io.BytesIO):
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _opener(body: bytes) -> Any:
    def opener(request: Any, timeout: float) -> _Response:
        assert request.get_header("User-agent") == f"netview/{__version__}"
        assert timeout == 10.0
        return _Response(body)

    return opener


def _raising(exc: Exception) -> Any:
    def opener(request: Any, timeout: float) -> _Response:
        raise exc

    return opener


def test_http_404_message() -> None:
    err = urllib.error.HTTPError(URL, 404, "Not Found", None, None)  # type: ignore[arg-type]
    with pytest.raises(CatalogUnavailableError, match=r"^Couldn't read the plugin list \(404\)$"):
        HttpCatalogFetcher(URL, opener=_raising(err)).fetch()


def test_unreachable_message() -> None:
    with pytest.raises(CatalogUnavailableError, match=r"^Couldn't reach GitHub$"):
        HttpCatalogFetcher(URL, opener=_raising(urllib.error.URLError("down"))).fetch()
    with pytest.raises(CatalogUnavailableError, match=r"^Couldn't reach GitHub$"):
        HttpCatalogFetcher(URL, opener=_raising(TimeoutError())).fetch()


def test_oversize_refused() -> None:
    with pytest.raises(CatalogUnavailableError, match="Couldn't read the plugin list"):
        HttpCatalogFetcher(URL, opener=_opener(b" " * 1_000_001)).fetch()


def test_valid_index_parses() -> None:
    index = bundled_index()
    body = json.dumps(index_to_dict(index)).encode()
    assert HttpCatalogFetcher(URL, opener=_opener(body)).fetch() == index
    assert HttpCatalogFetcher(URL).source == URL


def test_list_payload_refused() -> None:
    with pytest.raises(CatalogUnavailableError, match="Couldn't read the plugin list"):
        HttpCatalogFetcher(URL, opener=_opener(b"[]")).fetch()
    with pytest.raises(CatalogUnavailableError, match="Couldn't read the plugin list"):
        HttpCatalogFetcher(URL, opener=_opener(b"not json")).fetch()


def test_bundled_index_has_default_archive() -> None:
    assert build_index([], "main", DEFAULT_ARCHIVE_URL).archive_url == bundled_index().archive_url
