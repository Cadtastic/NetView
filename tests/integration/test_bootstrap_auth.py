from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import netview.bootstrap
import netview.presentation.cli as cli
from netview.application.usecases.auth.setup import SETUP_CODE_ALPHABET
from netview.bootstrap import build_container, create_application, print_setup_banner
from netview.infrastructure.settings import AppSettings
from netview.sdk.testing.fakes import FakeNetworkTools

runner = CliRunner()
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        netview.bootstrap, "SystemNetworkTools", lambda: FakeNetworkTools(gateway=None, fail=True)
    )


def _settings(tmp_path: Path, **extra: Any) -> AppSettings:
    return AppSettings(data_dir=tmp_path, **extra)


def test_container_wires_sign_in_and_seeds_the_builtin_roles(tmp_path: Path) -> None:
    container = build_container(_settings(tmp_path))
    try:
        auth = container.services.auth
        assert auth is not None
        roles = {view.role.id: view.role for view in auth.roles.list()}
        assert set(roles) == {"administrator", "default"}
        assert roles["default"].permissions == frozenset({"core.view"})
        assert auth.mode == "enterprise"
        assert auth.setup.status().open
        assert auth.policy.get().password_min_length == 12
        assert {g.owner for g in auth.catalog()} >= {"core"}
    finally:
        container.host.shutdown()
        container.engine.dispose()


def test_setup_code_is_made_once_per_process_in_enterprise_only(tmp_path: Path) -> None:
    enterprise = build_container(_settings(tmp_path / "a"))
    home = build_container(_settings(tmp_path / "b", mode="home"))
    try:
        code = enterprise.setup_code
        assert code is not None and len(code) == 8 and set(code) <= set(SETUP_CODE_ALPHABET)
        assert home.setup_code is None
        assert enterprise.setup_code == code
    finally:
        for c in (enterprise, home):
            c.host.shutdown()
            c.engine.dispose()


def test_banner_names_the_code_and_the_setup_address(capsys: pytest.CaptureFixture[str]) -> None:
    print_setup_banner(AppSettings(bind="0.0.0.0", port=9000), "ABCD2345")

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == lines[-1] == "=" * 46
    assert lines[1] == "NetView setup code: ABCD2345"
    assert lines[2] == "Open http://127.0.0.1:9000/setup to create the admin account."


def test_banner_brackets_an_ipv6_address(capsys: pytest.CaptureFixture[str]) -> None:
    print_setup_banner(AppSettings(bind="::1", port=8765), "ABCD2345")

    assert "http://[::1]:8765/setup" in capsys.readouterr().out


def test_serve_prints_setup_code_in_enterprise_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    create_application(_settings(tmp_path / "quiet"))  # not serving: nothing printed
    assert "setup code" not in capsys.readouterr().out

    create_application(_settings(tmp_path / "home", mode="home"), announce_setup=True)
    assert "setup code" not in capsys.readouterr().out

    create_application(_settings(tmp_path / "ent"), announce_setup=True)
    out = capsys.readouterr().out
    assert "NetView setup code: " in out and "/setup to create the admin account." in out


def test_no_banner_once_a_user_exists(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    first = build_container(_settings(tmp_path, mode="home"))
    try:
        assert first.services.auth is not None
        first.services.auth.setup.complete(None, "admin", PASSWORD, "127.0.0.1", "pytest")
    finally:
        first.host.shutdown()
        first.engine.dispose()

    create_application(_settings(tmp_path), announce_setup=True)

    assert "setup code" not in capsys.readouterr().out


def test_setup_with_the_printed_code_then_signed_in_requests_work(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = create_application(_settings(tmp_path), announce_setup=True)
    code = capsys.readouterr().out.split("NetView setup code: ")[1].split()[0]
    client = TestClient(app, base_url="http://localhost", headers={"X-Netview": "1"})

    assert client.get("/api/v1/state").status_code == 409  # not set up yet
    wrong = client.post("/api/v1/setup", json={"code": "AAAAAAAA", "username": "a", "password": PASSWORD})
    assert wrong.status_code == 401
    done = client.post("/api/v1/setup", json={"code": code, "username": "admin", "password": PASSWORD})
    assert done.status_code == 200, done.text
    assert client.get("/api/v1/state").status_code == 200
    anonymous = TestClient(app, base_url="http://localhost", headers={"X-Netview": "1"})
    assert anonymous.get("/api/v1/state").status_code == 401


def test_mode_env_and_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NETVIEW_MODE", "home")
    assert AppSettings(data_dir=tmp_path).mode == "home"
    monkeypatch.delenv("NETVIEW_MODE")
    assert AppSettings(data_dir=tmp_path).mode == "enterprise"

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        cli, "create_application", lambda settings, **kw: captured.setdefault("settings", settings)
    )
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: None)

    result = runner.invoke(cli.app, ["serve", "--data-dir", str(tmp_path), "--mode", "home"])
    assert result.exit_code == 0, result.output
    assert captured["settings"].mode == "home"

    monkeypatch.setenv("NETVIEW_MODE", "home")
    captured.clear()
    result = runner.invoke(cli.app, ["serve", "--data-dir", str(tmp_path), "--mode", "enterprise"])
    assert result.exit_code == 0, result.output
    assert captured["settings"].mode == "enterprise"  # the flag beats the environment

    bad = runner.invoke(cli.app, ["serve", "--data-dir", str(tmp_path), "--mode", "office"])
    assert bad.exit_code == 2
