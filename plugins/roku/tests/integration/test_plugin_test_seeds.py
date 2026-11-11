"""The shared way a test app loads the plugins folder must not start a real Roku scan."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

PLUGINS_DIR = Path(__file__).resolve().parents[3]


def _roku_job_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, seeds: dict[str, Any]) -> list[str]:
    from netview.bootstrap import build_container
    from netview.infrastructure.settings import AppSettings
    from netview.sdk.testing.fakes import FakeNetworkTools, FakeServiceProbes

    monkeypatch.setattr("netview.bootstrap.SystemNetworkTools", lambda: FakeNetworkTools())
    monkeypatch.setattr("netview.bootstrap.SystemServiceProbes", lambda **kw: FakeServiceProbes())
    container = build_container(
        AppSettings(data_dir=tmp_path, subnet="192.168.1.0/24", plugins=seeds, plugin_dirs=[PLUGINS_DIR])
    )
    try:
        plugin = container.host.plugin("roku")
        assert plugin is not None
        return [job.name for job in plugin.jobs()]
    finally:
        container.host.shutdown()
        container.engine.dispose()


def test_a_test_app_built_the_shared_way_has_no_roku_scan_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, plugin_seeds: Callable[..., dict[str, Any]]
) -> None:
    assert "scan" not in _roku_job_names(tmp_path, monkeypatch, plugin_seeds({"gsm7248": {"x": 1}}))


def test_the_default_seeds_do_start_a_roku_scan_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: without the shared seeds the scan job exists, so the test above proves something."""
    assert "scan" in _roku_job_names(tmp_path, monkeypatch, {})


def test_the_shared_seeds_keep_the_tests_own_values(plugin_seeds: Callable[..., dict[str, Any]]) -> None:
    own = {"gsm7248": {"host": "h"}, "roku": {"status_interval_s": 30}}
    seeds = plugin_seeds(own)
    assert seeds["gsm7248"] == {"host": "h"}
    assert seeds["roku"] == {"status_interval_s": 30, "auto_scan": "never"}
    assert own["roku"] == {"status_interval_s": 30}
