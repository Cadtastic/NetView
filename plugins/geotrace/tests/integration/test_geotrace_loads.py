"""GeoTrace loads Active from a plugin folder in a test app, and sets up with a files directory."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

PLUGINS_DIR = Path(__file__).resolve().parents[3]
GEOTRACE_GUID = "f64f43b1-9ff2-47b9-badf-390b2fef25db"


def test_the_plugin_loads_active_with_no_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plugin_seeds: Callable[..., dict[str, Any]]
) -> None:
    from netview.bootstrap import build_container
    from netview.infrastructure.settings import AppSettings
    from netview.sdk.testing.addresses import plugin_key
    from netview.sdk.testing.fakes import FakeNetworkTools, FakeServiceProbes

    monkeypatch.setattr("netview.bootstrap.SystemNetworkTools", lambda: FakeNetworkTools())
    monkeypatch.setattr("netview.bootstrap.SystemServiceProbes", lambda **kw: FakeServiceProbes())
    container = build_container(
        AppSettings(
            data_dir=tmp_path, subnet="192.168.1.0/24", plugins=plugin_seeds(), plugin_dirs=[PLUGINS_DIR]
        )
    )
    try:
        key = plugin_key(container.services, GEOTRACE_GUID)
        assert container.host.get(key).state == "active"
        plugin = container.host.plugin(key)
        assert plugin is not None
        assert plugin.jobs() == []
        files_dir = plugin.ctx.files_dir  # type: ignore[attr-defined]
        assert files_dir == tmp_path / "plugin-data" / GEOTRACE_GUID
        assert files_dir.is_dir()
    finally:
        container.host.shutdown()
        container.engine.dispose()
