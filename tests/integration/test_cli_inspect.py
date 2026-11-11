"""``netview inspect`` with a fake inspection plugin and no network."""

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import netview.bootstrap
from netview.infrastructure.plugins.discovery import DiscoveredPlugin
from netview.presentation.cli import app
from netview.sdk.testing.fakes import FakeNetworkTools

sys.path.insert(0, str(Path(__file__).parent / "plugins"))
from sample_plugins.inspector import InspectorPlugin

runner = CliRunner()


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        netview.bootstrap, "SystemNetworkTools", lambda: FakeNetworkTools(gateway=None, fail=True)
    )


@pytest.fixture
def with_inspector(offline: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        netview.bootstrap,
        "discover_plugin_classes",
        lambda extra_dirs=(): [DiscoveredPlugin("test:inspector", InspectorPlugin, None)],
    )


@pytest.fixture
def without_plugins(offline: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(netview.bootstrap, "discover_plugin_classes", lambda extra_dirs=(): [])


def test_inspect_prints_titles_and_text_lines_and_writes_the_report(
    with_inspector: None, tmp_path: Path
) -> None:
    out = tmp_path / "x.json"
    result = runner.invoke(
        app, ["inspect", "192.0.2.10", "--ports", "22,80", "--out", str(out), "--data-dir", str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert "Open ports" in lines
    assert lines[lines.index("Open ports") + 1] == "  22 ssh"
    assert lines[lines.index("Open ports") + 2] == "  80 http"
    # a section without "text" prints its data as indented JSON
    assert '  "vendor": "Acme"' in lines
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["schema"] == "netview/inspection@1"
    assert document["ip"] == "192.0.2.10"
    assert document["ports_spec"] == "22,80"
    assert [s["title"] for s in document["sections"]] == ["Open ports", "Raw facts"]


def test_inspect_defaults_to_the_top_ports(with_inspector: None, tmp_path: Path) -> None:
    out = tmp_path / "x.json"
    result = runner.invoke(app, ["inspect", "192.0.2.10", "--out", str(out), "--data-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert json.loads(out.read_text(encoding="utf-8"))["ports_spec"] == "top"


def test_an_invalid_ip_exits_2_before_building_anything(offline: None, tmp_path: Path) -> None:
    result = runner.invoke(app, ["inspect", "nope", "--data-dir", str(tmp_path)])
    assert result.exit_code == 2
    assert "nope" in result.output
    assert not (tmp_path / "netview.db").exists()


def test_an_invalid_port_spec_exits_2(with_inspector: None, tmp_path: Path) -> None:
    result = runner.invoke(app, ["inspect", "192.0.2.10", "--ports", "1-5; rm", "--data-dir", str(tmp_path)])
    assert result.exit_code == 2


def test_no_inspection_plugin_exits_1(without_plugins: None, tmp_path: Path) -> None:
    result = runner.invoke(app, ["inspect", "192.0.2.10", "--data-dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "no enabled plugin provides inspection" in result.output
