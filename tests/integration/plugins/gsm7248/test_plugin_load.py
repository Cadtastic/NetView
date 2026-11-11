from __future__ import annotations

from typing import Any

from netview.plugins.builtin.gsm7248.plugin import Gsm7248Plugin
from netview.plugins.builtin.gsm7248.settings import Gsm7248Settings
from netview.sdk import SDK_VERSION, Capability, Permission
from netview.sdk.testing.contract import check_plugin


def test_contract() -> None:
    check_plugin(Gsm7248Plugin)


def test_manifest() -> None:
    m = Gsm7248Plugin.manifest
    assert m.id == "gsm7248"
    assert m.name == "NETGEAR GSM7248"
    assert m.version == "0.1.0"
    assert m.sdk_version == ">=1.2,<2"
    assert SDK_VERSION == "1.2"
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


def test_registered_as_entry_point() -> None:
    import importlib.metadata

    found: dict[str, Any] = {
        ep.name: ep.value for ep in importlib.metadata.entry_points(group="netview.plugins")
    }
    assert found["gsm7248"] == "netview.plugins.builtin.gsm7248.plugin:Gsm7248Plugin"
