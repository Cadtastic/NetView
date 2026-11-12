import http.client
import io
import json
import stat
import urllib.error
import zipfile
from pathlib import Path
from typing import Any

import pytest

from netview.application.plugins.plugin_json import CatalogEntry, PluginJson
from netview.domain.errors import ConflictError, InstallError
from netview.infrastructure.plugins.installer import ZipPluginInstaller, extract_plugin

BASE = "top/plugins/demo/"
PLUGIN_JSON = {
    "schema": "netview.plugin/1",
    "id": "demo",
    "name": "Demo",
    "version": "0.1.0",
    "description": "d",
    "guid": "27bd9bf5-8dd2-4f12-bbe8-cfa490e3f85c",
    "display_name": "Demo",
    "plugin_type": "other",
    "sdk_version": ">=1.3,<2",
    "capabilities": ["api"],
    "permissions": ["api"],
    "requires": [],
}
ENTRY = CatalogEntry(
    PluginJson(
        "demo",
        "Demo",
        "0.1.0",
        "d",
        "27bd9bf5-8dd2-4f12-bbe8-cfa490e3f85c",
        "Demo",
        "other",
        ">=1.3,<2",
        ("api",),
        ("api",),
    ),
    "plugins/demo",
)


def _zip(path: Path, files: dict[str, str | bytes], symlinks: tuple[str, ...] = ()) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
        for name in symlinks:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "target")
    return path


def _good_files() -> dict[str, str | bytes]:
    return {
        "top/README.md": "repo",
        BASE + "__init__.py": "x = 1\n",
        BASE + "plugin.json": json.dumps(PLUGIN_JSON),
        BASE + "tests/test_demo.py": "def test(): ...\n",
        BASE + "__pycache__/x.pyc": b"\x00",
        BASE + "static/ui.js": "//",
        "top/plugins/other/__init__.py": "",
    }


class _Response(io.BytesIO):
    def __init__(self, data: bytes, length: bool = True) -> None:
        super().__init__(data)
        self.headers: dict[str, str] = {"Content-Length": str(len(data))} if length else {}

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _opener(data: bytes) -> Any:
    def opener(request: Any, timeout: float) -> _Response:
        return _Response(data)

    return opener


def _install(target: Path, files: dict[str, str | bytes], **kw: Any) -> list[tuple[str, int | None]]:
    archive = _zip(target.parent / "src.zip", files)
    calls: list[tuple[str, int | None]] = []
    installer = ZipPluginInstaller(target, opener=_opener(archive.read_bytes()), **kw)
    installer.install(ENTRY, "https://example.test/a.zip", lambda phase, pct: calls.append((phase, pct)))
    return calls


@pytest.fixture
def target(tmp_path: Path) -> Path:
    folder = tmp_path / "plugins"
    folder.mkdir()
    return folder


def _staging_empty(target: Path) -> bool:
    staging = target / ".staging"
    return not staging.exists() or not any(staging.iterdir())


def test_install_happy_path(target: Path) -> None:
    calls = _install(target, _good_files())
    assert (target / "demo" / "__init__.py").is_file()
    assert (target / "demo" / "plugin.json").is_file()
    assert (target / "demo" / "static" / "ui.js").is_file()
    assert not (target / "demo" / "tests").exists()
    assert not (target / "demo" / "__pycache__").exists()
    assert _staging_empty(target)
    downloading = [pct for phase, pct in calls if phase == "downloading"]
    assert downloading[-1] == 100
    assert calls[-1] == ("installing", None)


def _extract(tmp_path: Path, files: dict[str, str | bytes], **kw: Any) -> None:
    archive = _zip(tmp_path / "a.zip", files)
    extract_plugin(archive, "plugins/demo", tmp_path / "out", **kw)


def test_extract_refuses_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(InstallError):
        _extract(tmp_path, {BASE + "../../evil.py": "x", BASE + "__init__.py": ""})
    assert not (tmp_path / "top" / "evil.py").exists()


def test_extract_refuses_absolute(tmp_path: Path) -> None:
    with pytest.raises(InstallError):
        _extract(tmp_path, {"/etc/x": "x", BASE + "__init__.py": ""})


@pytest.mark.parametrize(
    "name",
    [BASE + "..\\x.py", "C:/x.py", BASE + "C:x.py", "\\\\server\\x"],
)
def test_extract_refuses_windows_paths(tmp_path: Path, name: str) -> None:
    with pytest.raises(InstallError):
        _extract(tmp_path, {name: "x", BASE + "__init__.py": ""})


def test_extract_refuses_symlink(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "a.zip", {BASE + "__init__.py": ""}, symlinks=(BASE + "link",))
    with pytest.raises(InstallError):
        extract_plugin(archive, "plugins/demo", tmp_path / "out")


def test_extract_stops_over_unpacked_cap(tmp_path: Path) -> None:
    with pytest.raises(InstallError):
        _extract(tmp_path, {BASE + "__init__.py": "x" * 11}, max_unpacked=10)


def test_install_refuses_wrong_id(target: Path) -> None:
    files = _good_files()
    files[BASE + "plugin.json"] = json.dumps({**PLUGIN_JSON, "id": "other"})
    with pytest.raises(InstallError):
        _install(target, files)
    assert not (target / "demo").exists()
    assert _staging_empty(target)


def test_install_refuses_missing_init(target: Path) -> None:
    files = _good_files()
    del files[BASE + "__init__.py"]
    with pytest.raises(InstallError):
        _install(target, files)
    assert not (target / "demo").exists()


def test_install_refuses_existing_folder(target: Path) -> None:
    (target / "demo").mkdir()
    (target / "demo" / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(ConflictError):
        _install(target, _good_files())
    assert [p.name for p in (target / "demo").iterdir()] == ["keep.txt"]
    assert _staging_empty(target)


def test_download_over_cap_refused(target: Path) -> None:
    with pytest.raises(InstallError):
        _install(target, _good_files(), max_download=10)
    assert not (target / "demo").exists()
    assert _staging_empty(target)


def test_download_over_cap_without_length_refused(target: Path) -> None:
    archive = _zip(target.parent / "src.zip", _good_files())

    def opener(request: Any, timeout: float) -> _Response:
        return _Response(archive.read_bytes(), length=False)

    installer = ZipPluginInstaller(target, opener=opener, max_download=10)
    with pytest.raises(InstallError):
        installer.install(ENTRY, "https://example.test/a.zip", lambda phase, pct: None)
    assert _staging_empty(target)


def test_unreachable_is_an_install_error(target: Path) -> None:
    def opener(request: Any, timeout: float) -> _Response:
        raise TimeoutError

    with pytest.raises(InstallError, match="Couldn't reach GitHub"):
        ZipPluginInstaller(target, opener=opener).install(
            ENTRY, "https://example.test/a.zip", lambda p, c: None
        )


def test_http_error_reports_status(target: Path) -> None:
    def opener(request: Any, timeout: float) -> _Response:
        raise urllib.error.HTTPError("https://example.test/a.zip", 404, "Not Found", None, None)  # type: ignore[arg-type]

    with pytest.raises(InstallError, match=r"Couldn't download the plugin \(404\)"):
        ZipPluginInstaller(target, opener=opener).install(
            ENTRY, "https://example.test/a.zip", lambda p, c: None
        )


def test_truncated_download_is_an_install_error(target: Path) -> None:
    def opener(request: Any, timeout: float) -> _Response:
        raise http.client.IncompleteRead(b"x")

    with pytest.raises(InstallError, match="Couldn't reach GitHub"):
        ZipPluginInstaller(target, opener=opener).install(
            ENTRY, "https://example.test/a.zip", lambda p, c: None
        )


def test_failure_leaves_no_folder(target: Path) -> None:
    files = _good_files()
    files[BASE + "../../evil.py"] = "x"
    with pytest.raises(InstallError):
        _install(target, files)
    assert not (target / "demo").exists()
    assert _staging_empty(target)
