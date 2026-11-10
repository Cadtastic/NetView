from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import netview.bootstrap
from netview.bootstrap import build_container, create_application
from netview.domain.errors import ValidationError
from netview.infrastructure.settings import AppSettings
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
    with TestClient(app, base_url="http://localhost", headers={"X-Netview": "1"}) as client:
        state = client.get("/api/v1/state").json()
        assert state["devices"] == []
        assert state["host"]["gateway"] is None
        jobs = {(j["owner"], j["name"]) for j in state["jobs"]}
        assert ("core", "scan") in jobs
        assert client.post("/api/v1/scan").status_code in (200, 409)
