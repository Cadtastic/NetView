from __future__ import annotations

import importlib.metadata
import shutil
from pathlib import Path

import pytest
from netview_local_plugins.gs105e.plugin import Gs105ePlugin
from netview_local_plugins.gs105e.settings import Gs105eSettings

from netview.sdk import SDK_VERSION, Capability, Permission
from netview.sdk.testing.contract import check_plugin


def test_contract() -> None:
    check_plugin(Gs105ePlugin)


def test_manifest() -> None:
    m = Gs105ePlugin.manifest
    assert m.id == "gs105e"
    assert m.name == "NETGEAR GS105E"
    assert m.version == "0.1.0"
    assert m.sdk_version == ">=1.3,<2"
    assert SDK_VERSION == "1.4"
    assert m.capabilities == {Capability.API, Capability.WEB_UI, Capability.STORAGE, Capability.JOBS}
    assert m.permissions == {
        Permission.DEVICES_READ,
        Permission.NAMES_WRITE,
        Permission.TYPES_WRITE,
        Permission.STORAGE_OWN,
        Permission.API,
        Permission.UI,
        Permission.NETWORK_PROBE,
    }
    assert Permission.TRAFFIC_WRITE not in m.permissions
    assert Capability.TRAFFIC not in m.capabilities


def test_settings_model_is_declared() -> None:
    assert Gs105ePlugin.settings_model is Gs105eSettings


def test_default_settings_register_only_prune() -> None:
    plugin = Gs105ePlugin()
    assert [j.name for j in plugin.jobs()] == ["prune"]
    plugin.settings = Gs105eSettings.model_validate({})
    assert [j.name for j in plugin.jobs()] == ["prune"]
    assert plugin.router() is not None
    assert plugin.ui() is not None
    assert plugin.storage() is not None


def test_transport_is_read_at_instance_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    from netview_local_plugins.gs105e import client

    sentinel = object()
    monkeypatch.setattr(client, "http_fetch", sentinel)
    assert Gs105ePlugin().fetch is sentinel


def test_it_is_not_built_in() -> None:
    found = {ep.name: ep.value for ep in importlib.metadata.entry_points(group="netview.plugins")}
    assert "gs105e" not in found


def test_the_folder_is_found_as_a_plugin(tmp_path: Path) -> None:
    from netview.infrastructure.plugins.discovery import discover_plugin_classes

    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source, tmp_path / "gs105e", ignore=shutil.ignore_patterns("__pycache__"))
    found = list(discover_plugin_classes(group="none", extra_dirs=[tmp_path]))
    assert [(d.error, d.cls.manifest.id if d.cls else None) for d in found] == [(None, "gs105e")]
