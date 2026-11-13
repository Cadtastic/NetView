"""Shared setup for the tests that live inside each plugin folder (``plugins/<id>/tests``).

NetView loads a folder plugin as ``netview_local_plugins.p<source_id>``. This file makes the folders here
importable as ``netview_local_plugins.<folder>``, so a plugin's tests can import its modules:
``from netview_local_plugins.gsm7248.settings import Gsm7248Settings``.

It also lends the plugin-host test harness of the core tests (``tests/integration/plugins/conftest.py``)
as the module ``netview_test_host`` and the ``env`` fixture. This file is not part of any plugin: it is
not copied when a plugin is installed.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from netview.infrastructure.plugins import discovery as discovery_module
from netview.infrastructure.plugins.discovery import LOCAL_PACKAGE, DiscoveredPlugin

PLUGINS_DIR = Path(__file__).resolve().parent
ROKU_GUID = "241d4d28-4a70-406c-833c-a7b4d5b389a9"
_HARNESS = PLUGINS_DIR.parent / "tests" / "integration" / "plugins" / "conftest.py"

if LOCAL_PACKAGE not in sys.modules:
    package = types.ModuleType(LOCAL_PACKAGE)
    package.__path__ = [str(PLUGINS_DIR)]
    sys.modules[LOCAL_PACKAGE] = package

if "netview_test_host" not in sys.modules:
    spec = importlib.util.spec_from_file_location("netview_test_host", _HARNESS)
    assert spec is not None and spec.loader is not None
    harness = importlib.util.module_from_spec(spec)
    sys.modules["netview_test_host"] = harness
    spec.loader.exec_module(harness)

from netview_test_host import env  # noqa: E402, F401 - the fixture, for every plugin test


def quiet_plugin_seeds(seeds: dict[str, dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """Plugin seeds (keyed by guid) for a test app that loads this whole folder, with Roku's startup scan off.

    Roku's default is a scan 5 s after start (an SSDP search and a port-8060 sweep of the real LAN), which
    any test that runs longer than that would otherwise trigger. ``seeds`` is the test's own, left unchanged.
    """
    merged = {guid: dict(values) for guid, values in (seeds or {}).items()}
    merged[ROKU_GUID] = {**merged.get(ROKU_GUID, {}), "auto_scan": "never"}
    return merged


@pytest.fixture
def plugin_seeds() -> Callable[..., dict[str, dict[str, Any]]]:
    """``quiet_plugin_seeds`` as a fixture: ``AppSettings(plugins=plugin_seeds({...}), ...)``."""
    return quiet_plugin_seeds


@pytest.fixture(autouse=True)
def _app_loads_the_modules_the_tests_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the app load a plugin from the same module objects the test imported.

    The host imports a folder as ``netview_local_plugins.p<source_id>``, a different name from the
    ``netview_local_plugins.<folder>`` the tests use, so a test's monkeypatch would miss the app's copy. When
    the test has already imported the folder, the app's name is pointed at those same modules.
    """
    real = discovery_module.import_folder

    def import_folder(folder: Path, source_id: int) -> DiscoveredPlugin:
        alias = f"{LOCAL_PACKAGE}.{folder.name}"
        if alias not in sys.modules:
            return real(folder, source_id)
        target = f"{LOCAL_PACKAGE}.p{source_id}"
        for name in [m for m in sys.modules if m == alias or m.startswith(alias + ".")]:
            sys.modules[target + name[len(alias) :]] = sys.modules[name]
        plugin_class = getattr(sys.modules[alias], "plugin_class", None)
        return discovery_module._check_class(f"folder:{folder.resolve()}", plugin_class, folder)

    monkeypatch.setattr("netview.infrastructure.plugins.host.import_folder", import_folder)
