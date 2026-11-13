from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import netview.bootstrap
from netview.bootstrap import build_container, create_application
from netview.domain.errors import ValidationError
from netview.infrastructure.settings import AppSettings
from netview.sdk.testing.auth import admin_cookies
from netview.sdk.testing.fakes import FakeNetworkTools


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No gateway, empty ARP table, failing ping: the machine has no network."""
    monkeypatch.setattr(
        netview.bootstrap, "SystemNetworkTools", lambda: FakeNetworkTools(gateway=None, fail=True)
    )


def _settings(tmp_path: Path, **extra: Any) -> AppSettings:
    return AppSettings(data_dir=tmp_path, **extra)


def test_default_subnet_is_local_ip_slash_24(offline: None, tmp_path: Path) -> None:
    container = build_container(_settings(tmp_path))
    assert str(container.subnet) == "192.168.1.0/24"


def test_configured_subnet_used(offline: None, tmp_path: Path) -> None:
    container = build_container(_settings(tmp_path, subnet="10.1.2.0/25"))
    assert str(container.subnet) == "10.1.2.0/25"


def test_oversized_subnet_rejected(offline: None, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        build_container(_settings(tmp_path, subnet="10.0.0.0/20"))


def test_invalid_subnet_rejected(offline: None, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        build_container(_settings(tmp_path, subnet="not a network"))


def test_application_starts_with_no_network(offline: None, tmp_path: Path) -> None:
    app = create_application(_settings(tmp_path))
    with TestClient(
        app,
        base_url="http://localhost",
        headers={"X-Netview": "1"},
        cookies=admin_cookies(app.state.services),
    ) as client:
        state = client.get("/api/v1/state").json()
        assert state["devices"] == []
        assert state["host"]["gateway"] is None
        jobs = {(j["owner"], j["name"]) for j in state["jobs"]}
        assert ("core", "scan") in jobs
        assert all("last_finished_ms" in j for j in state["jobs"])
        assert client.post("/api/v1/scan").status_code in (200, 409)


def test_bootstrap_creates_the_user_theme_folder_and_serves_it(offline: None, tmp_path: Path) -> None:
    app = create_application(_settings(tmp_path))
    themes = tmp_path / "themes"
    assert themes.is_dir()
    (themes / "mine.css").write_text(
        '/* netview-theme name="Mine" scheme="dark" preview="#000000,#111111,#222222" */\n'
    )
    with TestClient(
        app,
        base_url="http://localhost",
        headers={"X-Netview": "1"},
        cookies=admin_cookies(app.state.services),
    ) as client:
        body = client.get("/api/v1/themes").json()
        assert body["user_dir"] == str(themes)
        assert "user-mine" in [t["id"] for t in body["themes"]]
        assert client.get("/themes/user/mine.css").status_code == 200


def test_start_backs_up_then_rekeys_then_loads(offline: None, tmp_path: Path) -> None:
    """Order: backup, upgrade_core (re-key), host load. An old-id plugin_state row survives the whole way."""
    import sqlite3
    from datetime import date

    from sqlalchemy import text

    from netview.infrastructure.db.engine import make_engine
    from netview.infrastructure.db.migrate import upgrade_core

    health = "9f4cd689-1a67-4c89-abff-ac9252568d97"
    old = make_engine(f"sqlite:///{tmp_path / 'netview.db'}")
    upgrade_core(old, "0005")
    with old.begin() as c:
        c.execute(
            text("INSERT INTO plugin_state (plugin_id, enabled, settings_json) VALUES ('health', 0, '{}')")
        )
    old.dispose()

    container = build_container(_settings(tmp_path))
    try:
        info = next(p for p in container.host.list() if p.guid == health)
        assert info.state == "disabled"  # the old row, now under its guid, still applies
        with container.engine.connect() as c:
            assert (
                c.execute(
                    text("SELECT enabled FROM plugin_state WHERE plugin_id = :g"), {"g": health}
                ).scalar()
                == 0
            )
            assert (
                c.execute(text("SELECT count(*) FROM plugin_state WHERE plugin_id = 'health'")).scalar() == 0
            )
    finally:
        container.host.shutdown()
        container.engine.dispose()

    backup = tmp_path / f"netview.db.bak-{date.today().isoformat()}-before-plugin-identity"
    assert backup.is_file()
    con = sqlite3.connect(backup)
    try:
        assert con.execute("SELECT plugin_id FROM plugin_state").fetchall() == [
            ("health",)
        ]  # as it was before
    finally:
        con.close()
