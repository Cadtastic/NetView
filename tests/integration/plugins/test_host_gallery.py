import json
from pathlib import Path

import pytest
from conftest import HostEnv
from sample_plugins.good import GoodPlugin

from netview.domain.errors import ConflictError
from netview.infrastructure.plugins.discovery import discover_plugin_classes

OK_INIT = """
from netview.sdk import Capability, Permission, Plugin, PluginContext, PluginManifest


class FolderPlugin(Plugin):
    manifest = PluginManifest(
        id="{id}",
        name="Folder {id}",
        version="0.2.0",
        description="A folder plugin",
        sdk_version=">=1.0,<2",
        capabilities=frozenset({{Capability.API}}),
        permissions=frozenset({{Permission.API}}),
    )

    def setup(self, ctx: PluginContext) -> None: ...


plugin_class = FolderPlugin
"""


def _plugin_json(plugin_id: str) -> str:
    return json.dumps(
        {
            "schema": "netview.plugin/1",
            "id": plugin_id,
            "name": f"Folder {plugin_id}",
            "version": "0.2.0",
            "description": "A folder plugin",
            "sdk_version": ">=1.0,<2",
            "capabilities": ["api"],
            "permissions": ["api"],
        }
    )


def make_folder(base: Path, name: str, plugin_id: str | None = None, *, init: str | None = None) -> Path:
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text(init if init is not None else OK_INIT.format(id=name), "utf-8")
    if plugin_id is not None:
        (folder / "plugin.json").write_text(_plugin_json(plugin_id), "utf-8")
    return folder


def _host(env: HostEnv, base: Path):  # type: ignore[no-untyped-def]
    discovered = discover_plugin_classes(group="netview.test_none", extra_dirs=[base])
    return env.host([], extra=discovered, folders=[base])


def test_folder_plugin_reports_source_folder(env: HostEnv, tmp_path: Path) -> None:
    make_folder(tmp_path / "plugins", "gal_ok", "gal_ok")
    host = _host(env, tmp_path / "plugins")
    host.load_all()
    info = host.get("gal_ok")
    assert (info.state, info.source) == ("active", "folder")


def test_entry_point_plugin_reports_builtin(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    assert host.get("good").source == "builtin"


def test_failed_folder_with_plugin_json_shows_once_as_failed(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    make_folder(base, "gal_bad", "gal_bad", init="raise ImportError('nope')\n")
    host = _host(env, base)
    host.load_all()
    listed = [p for p in host.list() if p.id == "gal_bad"]
    assert len(listed) == 1
    assert listed[0].state == "failed"
    assert listed[0].error is not None and "ImportError" in listed[0].error
    assert listed[0].name == "Folder gal_bad"
    assert not [p for p in host.list() if p.state == "pending"]


def test_failed_folder_without_plugin_json_keeps_path_record(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    make_folder(base, "gal_bad2", None, init="raise ImportError('nope')\n")
    host = _host(env, base)
    host.load_all()
    assert next(p.id for p in host.list()).startswith("folder:")


def test_folder_added_after_start_is_pending(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    base.mkdir()
    host = _host(env, base)
    host.load_all()
    assert host.list() == []
    make_folder(base, "gal_new", "gal_new")
    pending = [p for p in host.list() if p.state == "pending"]
    assert [(p.id, p.source) for p in pending] == [("gal_new", "folder")]
    assert host.get("gal_new").state == "pending"


def test_pending_patch_is_conflict(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    base.mkdir()
    host = _host(env, base)
    host.load_all()
    make_folder(base, "gal_new", "gal_new")
    with pytest.raises(ConflictError):
        host.set_enabled("gal_new", False)
    with pytest.raises(ConflictError):
        host.update_settings("gal_new", {})


def test_dot_folders_are_skipped(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    make_folder(base / ".staging", "gal_stage", "gal_stage")
    host = _host(env, base)
    host.load_all()
    assert host.list() == []
