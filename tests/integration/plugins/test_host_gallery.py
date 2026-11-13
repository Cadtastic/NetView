import json
import uuid
from pathlib import Path

import pytest
from conftest import HostEnv
from sample_plugins.good import GoodPlugin

from netview.domain.errors import ConflictError
from netview.infrastructure.plugins.discovery import find_folders

OK_INIT = """
from netview.sdk import Capability, Permission, Plugin, PluginContext, PluginManifest, PluginType


class FolderPlugin(Plugin):
    manifest = PluginManifest(
        name="Folder {id}",
        version="0.2.0",
        description="A folder plugin",
        guid="{guid}",
        display_name="Folder {id}",
        plugin_type=PluginType.OTHER,
        sdk_version=">=2.0,<3",
        capabilities=frozenset({{Capability.API}}),
        permissions=frozenset({{Permission.API}}),
    )

    def setup(self, ctx: PluginContext) -> None: ...


plugin_class = FolderPlugin
"""


def _guid(plugin_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"netview-test:{plugin_id}"))


def _plugin_json(plugin_id: str) -> str:
    return json.dumps(
        {
            "schema": "netview.plugin/2",
            "name": f"Folder {plugin_id}",
            "version": "0.2.0",
            "description": "A folder plugin",
            "guid": _guid(plugin_id),
            "display_name": f"Folder {plugin_id}",
            "plugin_type": "other",
            "sdk_version": ">=2.0,<3",
            "capabilities": ["api"],
            "permissions": ["api"],
        }
    )


def make_folder(base: Path, name: str, plugin_id: str | None = None, *, init: str | None = None) -> Path:
    folder = base / name
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text(
        init if init is not None else OK_INIT.format(id=name, guid=_guid(name)), "utf-8"
    )
    if plugin_id is not None:
        (folder / "plugin.json").write_text(_plugin_json(plugin_id), "utf-8")
    return folder


def _host(env: HostEnv, base: Path):  # type: ignore[no-untyped-def]
    return env.host([], folder_bases=[(base, 1)])


def test_folder_plugin_reports_source_folder(env: HostEnv, tmp_path: Path) -> None:
    make_folder(tmp_path / "plugins", "gal_ok", "gal_ok")
    host = _host(env, tmp_path / "plugins")
    host.load_all()
    [info] = host.list()
    assert (info.state, info.source) == ("active", "folder")
    assert info.id == str(info.source_id)
    assert info.guid == _guid("gal_ok")


def test_entry_point_plugin_reports_builtin(env: HostEnv) -> None:
    host = env.host([GoodPlugin])
    host.load_all()
    assert host.get(env.id(GoodPlugin)).source == "builtin"


def test_failed_folder_with_plugin_json_shows_once_as_failed(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    make_folder(base, "gal_bad", "gal_bad", init="raise ImportError('nope')\n")
    host = _host(env, base)
    host.load_all()
    listed = [p for p in host.list() if p.guid == _guid("gal_bad")]
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
    assert [(p.guid, p.source) for p in pending] == [(_guid("gal_new"), "folder")]
    assert host.get(pending[0].id).state == "pending"


def test_pending_patch_is_conflict(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    base.mkdir()
    host = _host(env, base)
    host.load_all()
    make_folder(base, "gal_new", "gal_new")
    [pending] = host.list()
    with pytest.raises(ConflictError):
        host.set_enabled(pending.id, False)
    with pytest.raises(ConflictError):
        host.update_settings(pending.id, {})


def test_dot_folders_are_skipped(env: HostEnv, tmp_path: Path) -> None:
    base = tmp_path / "plugins"
    make_folder(base, ".staging", "gal_stage")
    assert find_folders([(base, 1)]) == []
    host = _host(env, base)
    host.load_all()
    assert host.list() == []
