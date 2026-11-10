from api_helpers import ApiWorld, make_app, make_client
from fastapi.testclient import TestClient

from netview.presentation.api.app import create_app

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)


def test_host_header_rejected(client: TestClient) -> None:
    assert client.get("/api/v1/state", headers={"Host": "evil.example"}).status_code == 403


def test_localhost_with_port_allowed(client: TestClient) -> None:
    assert client.get("/api/v1/state", headers={"Host": "localhost:8765"}).status_code == 200


def test_ipv6_loopback_with_port_allowed(client: TestClient) -> None:
    assert client.get("/api/v1/state", headers={"Host": "[::1]:8765"}).status_code == 200


def test_configured_bind_address_allowed(world: ApiWorld) -> None:
    app = create_app(world.services, [], [], {"localhost", "192.168.1.95"})
    assert make_client(app).get("/api/v1/state", headers={"Host": "192.168.1.95:9000"}).status_code == 200


def test_post_without_header_forbidden(world: ApiWorld) -> None:
    bare = make_client(make_app(world), with_header=False)
    assert bare.post("/api/v1/watches", json={"spec": "192.168.1.5"}).status_code == 403


def test_get_needs_no_header(world: ApiWorld) -> None:
    assert make_client(make_app(world), with_header=False).get("/api/v1/state").status_code == 200


def test_csp_header_present(client: TestClient) -> None:
    response = client.get("/api/v1/state")
    assert response.headers["content-security-policy"] == CSP
    assert response.headers["x-content-type-options"] == "nosniff"


def test_csp_on_rejected_requests(client: TestClient) -> None:
    response = client.get("/api/v1/state", headers={"Host": "evil.example"})
    assert response.headers["content-security-policy"] == CSP


def test_docs_served_without_cdn(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "/static/swagger/" in response.text
    assert "cdn.jsdelivr" not in response.text
    assert "<script>" not in response.text  # the CSP forbids inline scripts
    assert client.get("/static/swagger/swagger-ui-bundle.js").status_code == 200
    assert client.get("/docs/init.js").status_code == 200


def test_index_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
