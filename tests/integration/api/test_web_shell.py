import re

import pytest
from fastapi.testclient import TestClient

MODULES = [
    "main",
    "api",
    "slots",
    "util",
    "table-model",
    "pages/dashboard",
    "pages/devices",
    "theme",
    "icons",
    "toast",
    "settings/dialog",
    "settings/appearance",
    "settings/plugins-tab",
    "settings/schema-form",
]


def test_index_loads_the_app_as_a_module_with_no_inline_script(client: TestClient) -> None:
    html = client.get("/").text
    assert '<script type="module" src="/static/js/main.js"></script>' in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)  # the CSP forbids inline scripts
    assert not re.search(r"\son\w+=", html)  # and inline event handlers


@pytest.mark.parametrize("name", MODULES)
def test_script_modules_are_served(client: TestClient, name: str) -> None:
    response = client.get(f"/static/js/{name}.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_old_plugins_page_is_gone(client: TestClient) -> None:
    assert client.get("/static/js/pages/plugins.js").status_code == 404


def test_top_bar_has_a_labelled_settings_button_and_no_theme_toggle(client: TestClient) -> None:
    html = client.get("/").text
    assert re.search(r'<button[^>]*id="btnSettings"[^>]*aria-label="Settings"', html)
    assert "btnTheme" not in html
    assert 'class="topbar"' in html


def test_stylesheet_is_served(client: TestClient) -> None:
    assert client.get("/static/css/app.css").status_code == 200


@pytest.mark.parametrize("name", ["daylight", "graphite", "harbor", "contrast"])
def test_builtin_theme_files_are_served(client: TestClient, name: str) -> None:
    response = client.get(f"/static/themes/{name}.css")
    assert response.status_code == 200
    assert "css" in response.headers["content-type"]


@pytest.mark.parametrize("path", ["/login", "/setup"])
def test_auth_pages_are_served_with_csp_and_no_inline_script(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "content-security-policy" in response.headers
    html = response.text
    assert re.search(r'<script type="module" src="/static/js/auth/\w+\.js"></script>', html)
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\son\w+=", html)


@pytest.mark.parametrize("name", ["auth", "auth/login", "auth/setup", "auth/password-dialog"])
def test_auth_modules_are_served(client: TestClient, name: str) -> None:
    assert client.get(f"/static/js/{name}.js").status_code == 200


def test_top_bar_has_an_account_button_after_settings(client: TestClient) -> None:
    html = client.get("/").text
    assert html.index('id="btnSettings"') < html.index('id="btnAccount"')
