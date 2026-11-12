import uuid
from typing import Any

import pytest

from netview.application.plugins.plugin_json import (
    DEFAULT_ARCHIVE_URL,
    PluginJson,
    build_index,
    index_to_dict,
    parse_index,
)
from netview.domain.errors import ValidationError


def _pj(plugin_id: str) -> PluginJson:
    return PluginJson(
        id=plugin_id,
        name=plugin_id.title(),
        version="0.1.0",
        description="d",
        guid=str(uuid.uuid5(uuid.NAMESPACE_DNS, plugin_id)),
        display_name=plugin_id.title(),
        plugin_type="other",
        sdk_version=">=1.3,<2",
        capabilities=("api",),
        permissions=("api",),
    )


def _data(*ids: str) -> dict[str, Any]:
    data = index_to_dict(build_index([_pj(i) for i in ids], "main", DEFAULT_ARCHIVE_URL))
    assert isinstance(data, dict)
    return data


def test_index_round_trip() -> None:
    index = build_index([_pj("b"), _pj("a")], "main", DEFAULT_ARCHIVE_URL)
    assert parse_index(index_to_dict(index)) == index


def test_index_sorted_by_id() -> None:
    index = build_index([_pj("zed"), _pj("alpha")], "main", DEFAULT_ARCHIVE_URL)
    assert [e.plugin.id for e in index.plugins] == ["alpha", "zed"]
    assert [e.path for e in index.plugins] == ["plugins/alpha", "plugins/zed"]


def test_index_rejects_path_mismatch() -> None:
    data = _data("a")
    data["plugins"][0]["path"] = "plugins/other"
    with pytest.raises(ValidationError):
        parse_index(data)


def test_index_rejects_duplicate_ids() -> None:
    data = _data("a")
    data["plugins"].append(dict(data["plugins"][0]))
    with pytest.raises(ValidationError):
        parse_index(data)


@pytest.mark.parametrize("reserved", ["catalog", "install"])
def test_index_rejects_reserved_id(reserved: str) -> None:
    with pytest.raises(ValidationError, match="reserved"):
        parse_index(_data(reserved))


def test_index_rejects_wrong_schema() -> None:
    data = _data("a")
    data["schema"] = "netview.plugin-index/9"
    with pytest.raises(ValidationError):
        parse_index(data)


def test_index_rejects_non_object() -> None:
    with pytest.raises(ValidationError):
        parse_index([])


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/x.zip",
        "http://localhost.evil.example/x.zip",
        "http://127.0.0.1.attacker.net/x.zip",
    ],
)
def test_index_rejects_plain_http_archive(url: str) -> None:
    data = _data("a")
    data["archive_url"] = url
    with pytest.raises(ValidationError):
        parse_index(data)


def test_index_allows_local_http_archive() -> None:
    data = _data("a")
    data["archive_url"] = "http://127.0.0.1:8123/x.zip"
    assert parse_index(data).archive_url == "http://127.0.0.1:8123/x.zip"
