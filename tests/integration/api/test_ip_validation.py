"""Review fix M19: IPv4 validation at the API edge."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("bad", ["not-an-ip", "999.1.1.1", "1.2.3.4; calc", "", "::1"])
def test_inspection_rejects_a_bad_ip(client: TestClient, bad: str) -> None:
    response = client.post("/api/v1/inspections", json={"ip": bad})
    assert response.status_code == 422


def test_latest_inspection_rejects_a_bad_ip(client: TestClient) -> None:
    assert client.get("/api/v1/inspections/not-an-ip").status_code == 422


def test_inspection_accepts_a_valid_ip(client: TestClient) -> None:
    response = client.post("/api/v1/inspections", json={"ip": "192.168.1.5"})
    assert response.status_code != 422
