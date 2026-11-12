"""Review fix M21: serve options, graceful shutdown and the SDK version home."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import netview.presentation.cli as cli
from netview.application.plugins.manifest import SDK_VERSION
from netview.sdk import SDK_VERSION as SDK_REEXPORT

runner = CliRunner()


def test_serve_maps_options_to_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(cli, "create_application", lambda settings: captured.setdefault("settings", settings))
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: captured.setdefault("kwargs", kw))

    result = runner.invoke(
        cli.app,
        ["serve", "--data-dir", str(tmp_path), "--subnet", "10.1.2.0/24", "--interval", "12", "--fast", "3"],
    )

    assert result.exit_code == 0, result.output
    settings = captured["settings"]
    assert settings.subnet == "10.1.2.0/24"
    assert settings.scan_interval_s == 12
    assert settings.fast_interval_s == 3
    assert captured["kwargs"]["timeout_graceful_shutdown"] == 3
    assert settings.plugin_dirs == []


def test_serve_takes_extra_plugin_folders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(cli, "create_application", lambda settings: captured.setdefault("settings", settings))
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: None)
    one, two = tmp_path / "one", tmp_path / "two"

    result = runner.invoke(
        cli.app, ["serve", "--data-dir", str(tmp_path), "--plugin-dir", str(one), "--plugin-dir", str(two)]
    )

    assert result.exit_code == 0, result.output
    assert captured["settings"].plugin_dirs == [one, two]


PLUGIN_SOURCE = """
from netview.sdk import Capability, Plugin, PluginManifest


class Sample(Plugin):
    manifest = PluginManifest(
        id="{id}", name="Sample", version="1", description="", sdk_version=">=1,<2",
        capabilities=frozenset(), permissions=frozenset(),
    )

    def setup(self, ctx):
        return None


plugin_class = Sample
"""


def _install(folder: Path, plugin_id: str) -> None:
    (folder / plugin_id).mkdir(parents=True)
    (folder / plugin_id / "__init__.py").write_text(PLUGIN_SOURCE.format(id=plugin_id), encoding="utf-8")


def test_plugin_folders_are_the_data_dir_one_then_the_configured_ones(tmp_path: Path) -> None:
    from netview.bootstrap import plugin_folders
    from netview.infrastructure.settings import AppSettings

    extra = tmp_path / "extra"
    settings = AppSettings(data_dir=tmp_path / "data", plugin_dirs=[extra, tmp_path / "data" / "plugins"])
    assert plugin_folders(settings) == [tmp_path / "data" / "plugins", extra]
    assert (tmp_path / "data" / "plugins").is_dir()  # made on first use, so there is somewhere to copy to


def test_a_plugin_copied_into_the_data_dir_is_loaded_and_the_optional_ones_are_not_built_in(
    tmp_path: Path,
) -> None:
    from netview.bootstrap import build_container
    from netview.infrastructure.settings import AppSettings

    _install(tmp_path / "plugins", "copied_in")
    _install(tmp_path / "elsewhere", "pointed_at")
    container = build_container(
        AppSettings(data_dir=tmp_path, subnet="192.0.2.0/24", plugin_dirs=[tmp_path / "elsewhere"])
    )
    try:
        states = {p.id: p.state for p in container.host.list()}
    finally:
        container.host.shutdown()
        container.engine.dispose()
    assert states["copied_in"] == "active"
    assert states["pointed_at"] == "active"
    assert "gsm7248" not in states
    assert "starlink" not in states
    assert {"lan_discovery", "health", "identity", "local_host", "inspection"} <= set(states)


def test_sdk_version_lives_in_application_and_is_reexported() -> None:
    assert SDK_VERSION == SDK_REEXPORT == "1.5"
