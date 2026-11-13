import uuid
from typing import Any

import pytest

from netview.application.plugins.plugin_json import (
    DEFAULT_ARCHIVE_URL,
    CatalogEntry,
    PluginJson,
    build_index,
    index_to_dict,
    parse_index,
)
from netview.domain.errors import ValidationError


def _pj(plugin_id: str) -> PluginJson:
    return PluginJson(
        name=plugin_id.title(),
        version="0.1.0",
        description="d",
        guid=str(uuid.uuid5(uuid.NAMESPACE_DNS, plugin_id)),
        display_name=plugin_id.title(),
        plugin_type="other",
        sdk_version=">=2.0,<3",
        capabilities=("api",),
        permissions=("api",),
    )


def _entry(name: str) -> CatalogEntry:
    return CatalogEntry(_pj(name), f"plugins/{name}")


def _data(*ids: str) -> dict[str, Any]:
    data = index_to_dict(
        build_index([CatalogEntry(_pj(i), f"plugins/{i}") for i in ids], "main", DEFAULT_ARCHIVE_URL)
    )
    assert isinstance(data, dict)
    return data


def test_index_round_trip() -> None:
    index = build_index([_entry("b"), _entry("a")], "main", DEFAULT_ARCHIVE_URL)
    assert parse_index(index_to_dict(index)) == index


def test_index_sorted_by_path() -> None:
    index = build_index([_entry("zed"), _entry("alpha")], "main", DEFAULT_ARCHIVE_URL)
    assert [e.plugin.name for e in index.plugins] == ["Alpha", "Zed"]
    assert [e.path for e in index.plugins] == ["plugins/alpha", "plugins/zed"]


@pytest.mark.parametrize(
    "path",
    [
        "plugins/",
        "plugins/Bad",
        "plugins/a/b",
        "plugins/../x",
        "other/a",
        "plugins/-a",
        "plugins/a b",
        "a",
        "",
    ],
)
def test_index_rejects_bad_path(path: str) -> None:
    data = _data("a")
    data["plugins"][0]["path"] = path
    with pytest.raises(ValidationError, match="path"):
        parse_index(data)


def test_index_rejects_missing_path() -> None:
    data = _data("a")
    del data["plugins"][0]["path"]
    with pytest.raises(ValidationError, match="path"):
        parse_index(data)


def test_index_accepts_any_clean_folder_name() -> None:
    data = _data("a")
    data["plugins"][0]["path"] = "plugins/some_folder-2"
    assert parse_index(data).plugins[0].path == "plugins/some_folder-2"


def test_index_rejects_duplicate_guid() -> None:
    data = _data("a")
    twin = dict(data["plugins"][0])
    twin["path"] = "plugins/b"
    data["plugins"].append(twin)
    with pytest.raises(ValidationError, match="duplicate guid"):
        parse_index(data)


def test_index_rejects_an_id_key() -> None:
    data = _data("a")
    data["plugins"][0]["id"] = "a"
    with pytest.raises(ValidationError, match="unknown field id"):
        parse_index(data)


def test_index_schema_is_2() -> None:
    assert _data("a")["schema"] == "netview.plugin-index/2"


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
