from __future__ import annotations

from pathlib import Path
from typing import Any

from netview_local_plugins.gsm7248.plugin import Gsm7248Plugin
from netview_local_plugins.gsm7248.settings import Gsm7248Settings

from netview.sdk import SDK_VERSION, Capability, Permission
from netview.sdk.testing.contract import check_plugin


def test_contract() -> None:
    check_plugin(Gsm7248Plugin)


def test_manifest() -> None:
    m = Gsm7248Plugin.manifest
    assert m.id == "gsm7248"
    assert m.name == "NETGEAR GSM7248"
    assert m.version == "0.1.0"
    assert m.sdk_version == ">=1.3,<2"
    assert SDK_VERSION == "1.3"
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


def test_settings_model_is_declared() -> None:
    assert Gsm7248Plugin.settings_model is Gsm7248Settings


def test_it_is_not_built_in() -> None:
    import importlib.metadata

    found: dict[str, Any] = {
        ep.name: ep.value for ep in importlib.metadata.entry_points(group="netview.plugins")
    }
    assert "gsm7248" not in found


def test_the_folder_is_found_as_a_plugin(tmp_path: Path) -> None:
    """Installing is copying the folder: a copy in a plugins folder is discovered, tests folder and all."""
    import shutil

    from netview.infrastructure.plugins.discovery import discover_plugin_classes

    source = Path(__file__).resolve().parents[2]
    shutil.copytree(source, tmp_path / "gsm7248", ignore=shutil.ignore_patterns("__pycache__"))
    found = [d for d in discover_plugin_classes(group="none", extra_dirs=[tmp_path])]
    assert [(d.error, d.cls.manifest.id if d.cls else None) for d in found] == [(None, "gsm7248")]
