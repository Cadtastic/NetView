"""Shared setup for the tests that live inside each plugin folder (``plugins/<id>/tests``).

NetView loads a folder plugin as ``netview_local_plugins.<folder>``. This file makes the folders here
importable under that same name, so a plugin's tests import its modules the way the running app does:
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

from netview.infrastructure.plugins.discovery import LOCAL_PACKAGE

PLUGINS_DIR = Path(__file__).resolve().parent
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
    """Plugin seeds for a test app that loads this whole folder, with the Roku startup scan switched off.

    Roku's default is a scan 5 s after start (an SSDP search and a port-8060 sweep of the real LAN), which
    any test that runs longer than that would otherwise trigger. ``seeds`` is the test's own, left unchanged.
    """
    merged = {plugin_id: dict(values) for plugin_id, values in (seeds or {}).items()}
    merged["roku"] = {**merged.get("roku", {}), "auto_scan": "never"}
    return merged


@pytest.fixture
def plugin_seeds() -> Callable[..., dict[str, dict[str, Any]]]:
    """``quiet_plugin_seeds`` for a test: ``AppSettings(plugins=plugin_seeds({...}), plugin_dirs=[PLUGINS])``."""
    return quiet_plugin_seeds
