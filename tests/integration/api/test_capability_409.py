from fastapi.testclient import TestClient


def test_inspection_without_provider_409(client: TestClient) -> None:
    response = client.post("/api/v1/inspections", json={"ip": "192.168.1.5", "ports": "top"})
    assert response.status_code == 409
    assert response.json() == {"error": "no enabled plugin provides inspection"}


def test_scan_without_provider_409(client: TestClient) -> None:
    response = client.post("/api/v1/scan")
    assert response.status_code == 409
    assert response.json() == {"error": "no enabled plugin provides discovery"}


def test_latest_inspection_missing_404(client: TestClient) -> None:
    assert client.get("/api/v1/inspections/192.168.1.5").status_code == 404
