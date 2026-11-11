"""Load the plugin the way netview does, so tests import ``netview_local_plugins.roku.<module>``.

This runs at conftest import time, before the test modules are collected and import the plugin.
"""

from __future__ import annotations

from pathlib import Path

from netview.infrastructure.plugins.discovery import discover_plugin_classes

ROKU_DIR = Path(__file__).resolve().parents[1]
PLUGINS_DIR = ROKU_DIR.parent

DISCOVERED = discover_plugin_classes(extra_dirs=[PLUGINS_DIR])
