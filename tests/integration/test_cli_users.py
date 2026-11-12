from pathlib import Path

import pytest
from typer.testing import CliRunner

import netview.bootstrap
from netview.application.auth.principal import SYSTEM_PRINCIPAL
from netview.bootstrap import Container, build_container
from netview.domain.auth import ADMIN_ROLE
from netview.infrastructure.settings import AppSettings
from netview.presentation.cli import app
from netview.sdk.testing.fakes import FakeNetworkTools

runner = CliRunner()
PASSWORD = "correct horse battery"
NEW_PASSWORD = "another long passphrase"


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        netview.bootstrap, "SystemNetworkTools", lambda: FakeNetworkTools(gateway=None, fail=True)
    )


def _container(data: Path) -> Container:
    return build_container(AppSettings(data_dir=data, mode="home"))


def _close(container: Container) -> None:
    container.host.shutdown()
    container.engine.dispose()


def _setup(data: Path) -> None:
    """The first-run setup, done the way the web page does it, then a second user."""
    container = _container(data)
    try:
        auth = container.services.auth
        assert auth is not None
        auth.setup.complete(None, "Admin", PASSWORD, "127.0.0.1", "pytest")
        auth.users.create_local(SYSTEM_PRINCIPAL, "kdoe", "K Doe", PASSWORD, {"default"})
    finally:
        _close(container)


def _user_id(container: Container, username: str) -> int:
    auth = container.services.auth
    assert auth is not None
    return next(u.id for u in auth.users.list() if u.username == username)


def test_users_list_after_setup(tmp_path: Path) -> None:
    _setup(tmp_path)

    result = runner.invoke(app, ["users", "list", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].split() == ["username", "provider", "roles", "enabled", "last", "sign-in"]
    admin = next(line for line in lines if line.startswith("admin")).split()
    assert admin[:4] == ["admin", "local", ADMIN_ROLE, "yes"]
    assert admin[4] != "never"  # setup signed the administrator in
    kdoe = next(line for line in lines if line.startswith("kdoe")).split()
    assert kdoe[:4] == ["kdoe", "local", "default", "yes"]
    assert kdoe[4] == "never"


def test_reset_password_prompts_twice_and_ends_sessions(tmp_path: Path) -> None:
    _setup(tmp_path)
    container = _container(tmp_path)
    try:
        auth = container.services.auth
        assert auth is not None
        token = auth.sessions.create(_user_id(container, "kdoe"), "127.0.0.1", "pytest")
        assert auth.sessions.resolve(token) is not None
    finally:
        _close(container)

    result = runner.invoke(
        app,
        ["users", "reset-password", "KDoe", "--data-dir", str(tmp_path)],
        input=f"{NEW_PASSWORD}\n{NEW_PASSWORD}\n",
    )

    assert result.exit_code == 0, result.output
    assert "New password" in result.output and "Repeat for confirmation" in result.output
    assert NEW_PASSWORD not in result.output  # typed with echo off
    container = _container(tmp_path)
    try:
        auth = container.services.auth
        assert auth is not None
        assert auth.sessions.resolve(token) is None
        signed_in = auth.sign_in("kdoe", NEW_PASSWORD, "127.0.0.1", "pytest")
        assert not signed_in.principal.must_change_password  # the admin chose it at the console
    finally:
        _close(container)


def test_reset_password_refuses_a_short_password(tmp_path: Path) -> None:
    _setup(tmp_path)

    result = runner.invoke(
        app, ["users", "reset-password", "kdoe", "--data-dir", str(tmp_path)], input="short\nshort\n"
    )

    assert result.exit_code == 1
    assert "at least 12" in result.output


def test_reset_password_unknown_user_exit_code_1(tmp_path: Path) -> None:
    _setup(tmp_path)

    result = runner.invoke(
        app, ["users", "reset-password", "nobody", "--data-dir", str(tmp_path)], input="x\nx\n"
    )

    assert result.exit_code == 1
    assert "no user named 'nobody'" in result.output
    assert "New password" not in result.output  # nothing is asked for a user who does not exist


def test_enable_reenables_disabled_user(tmp_path: Path) -> None:
    _setup(tmp_path)
    container = _container(tmp_path)
    try:
        auth = container.services.auth
        assert auth is not None
        auth.users.update(SYSTEM_PRINCIPAL, _user_id(container, "kdoe"), enabled=False)
    finally:
        _close(container)

    result = runner.invoke(app, ["users", "enable", "kdoe", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    container = _container(tmp_path)
    try:
        auth = container.services.auth
        assert auth is not None
        assert next(u for u in auth.users.list() if u.username == "kdoe").enabled
    finally:
        _close(container)


def test_enable_refuses_the_builtin_admin(tmp_path: Path) -> None:
    _setup(tmp_path)

    result = runner.invoke(app, ["users", "enable", "admin", "--data-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "the built-in admin can't be disabled, so there is nothing to enable" in result.output
