import json
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

import netview.bootstrap
from netview.domain.device import Device, DeviceStatus
from netview.infrastructure.db.engine import make_engine
from netview.infrastructure.db.migrate import upgrade_core
from netview.infrastructure.db.uow import SqlUnitOfWork
from netview.presentation.cli import app
from netview.sdk.testing.fakes import FakeNetworkTools, PingResult

FIXTURES = Path(__file__).parent.parent / "fixtures" / "lanmon"
runner = CliRunner()


@pytest.fixture
def fake_network(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = FakeNetworkTools(
        replies={"192.168.1.1": PingResult(1.5, 64)},
        arp={"192.168.1.1": "aa:bb:cc:dd:ee:01", "192.168.1.7": "aa:bb:cc:dd:ee:07"},
    )
    monkeypatch.setattr(netview.bootstrap, "SystemNetworkTools", lambda: tools)


def _set_nickname(data_dir: Path, key: str, value: str) -> None:
    engine = make_engine(f"sqlite:///{data_dir / 'netview.db'}")
    upgrade_core(engine)
    with SqlUnitOfWork(sessionmaker(engine)) as u:
        u.devices.add(Device(key, "192.168.1.20", key, "", 1, 1, DeviceStatus.OFFLINE))
        u.nicknames.set(key, value)
        u.commit()
    engine.dispose()


def test_cli_import_exit_code_on_conflict(fake_network: None, tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    _set_nickname(data, "aa:bb:cc:00:00:01", "Mine")
    store = str(FIXTURES / "store_basic.json")
    args = ["import-lanmon", store, "--data-dir", str(data)]

    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert 'aa:bb:cc:00:00:01: netview="Mine" source="Jessi\'s Kindle"' in result.output

    forced = runner.invoke(app, [*args, "--prefer-source"])
    assert forced.exit_code == 0, forced.output


def test_cli_import_dry_run_reports_counts(fake_network: None, tmp_path: Path) -> None:
    store = str(FIXTURES / "store_basic.json")
    result = runner.invoke(app, ["import-lanmon", store, "--data-dir", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "devices added: 2" in result.output


def test_cli_scan_once_list(fake_network: None, tmp_path: Path) -> None:
    out = tmp_path / "state.json"
    result = runner.invoke(app, ["scan", "--once", "--list", "--data-dir", str(tmp_path), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "2 devices (1 replied, 1 ARP only) in " in result.output
    assert "192.168.1.1  aa:bb:cc:dd:ee:01" in result.output
    assert "192.168.1.7  aa:bb:cc:dd:ee:07" in result.output
    state = json.loads(out.read_text(encoding="utf-8"))
    assert state["schema"] == "netview/state@1"
    assert {d["ip"] for d in state["devices"]} == {"192.168.1.1", "192.168.1.7"}


def test_cli_scan_requires_once(fake_network: None, tmp_path: Path) -> None:
    result = runner.invoke(app, ["scan", "--data-dir", str(tmp_path)])
    assert result.exit_code != 0


def test_cli_plugins_list_and_db_upgrade(fake_network: None, tmp_path: Path) -> None:
    upgraded = runner.invoke(app, ["db", "upgrade", "--data-dir", str(tmp_path)])
    assert upgraded.exit_code == 0, upgraded.output
    listed = runner.invoke(app, ["plugins", "list", "--data-dir", str(tmp_path)])
    assert listed.exit_code == 0, listed.output
    assert "lan_discovery" in listed.output
    assert "active" in listed.output
