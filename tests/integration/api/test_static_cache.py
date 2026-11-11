"""Static files must be revalidated on every load, so an upgrade never runs stale JavaScript."""

from pathlib import Path

import pytest
from api_helpers import ApiWorld, make_app, make_client
from fastapi.testclient import TestClient

from netview.application.plugins.ui import UiContribution


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/static/js/main.js",
        "/static/js/settings/dialog.js",
        "/static/css/app.css",
        "/static/swagger/swagger-ui.css",
        "/docs/init.js",
    ],
)
def test_core_files_say_no_cache(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_plugin_static_files_say_no_cache(world: ApiWorld, tmp_path: Path) -> None:
    (tmp_path / "ui.js").write_text("export default 1;")
    client = make_client(make_app(world, ui=[("demo", UiContribution(tmp_path))]))
    response = client.get("/plugins/demo/static/ui.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_revalidation_is_a_cheap_304_that_still_says_no_cache(client: TestClient) -> None:
    first = client.get("/static/js/main.js")
    again = client.get("/static/js/main.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "no-cache"


def test_a_missing_file_is_still_404(client: TestClient) -> None:
    assert client.get("/static/js/nope.js").status_code == 404
