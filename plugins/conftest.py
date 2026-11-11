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
from pathlib import Path

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
