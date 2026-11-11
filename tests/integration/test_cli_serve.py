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


def test_sdk_version_lives_in_application_and_is_reexported() -> None:
    assert SDK_VERSION == SDK_REEXPORT == "1.4"


def test_serve_plugin_dir_is_repeatable_and_appends(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(cli, "create_application", lambda settings: captured.setdefault("settings", settings))
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: None)
    monkeypatch.setenv("NETVIEW_PLUGIN_DIRS", '["from-env"]')
    one, two = tmp_path / "one", tmp_path / "two"

    result = runner.invoke(
        cli.app,
        ["serve", "--data-dir", str(tmp_path), "--plugin-dir", str(one), "--plugin-dir", str(two)],
    )

    assert result.exit_code == 0, result.output
    assert captured["settings"].plugin_dirs == [Path("from-env"), one, two]
