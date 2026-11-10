from pathlib import Path

from api_helpers import build_world, make_app, make_client
from fastapi.testclient import TestClient

from netview.infrastructure.themes import FolderThemeCatalog

HEADER = '/* netview-theme name="Mine" scheme="light" preview="#ffffff,#eeeeee,#336699" */\n:root{}\n'


def make(tmp_path: Path) -> tuple[TestClient, Path]:
    builtin = tmp_path / "builtin"
    user = tmp_path / "data" / "themes"
    builtin.mkdir()
    user.mkdir(parents=True)
    (builtin / "daylight.css").write_text(HEADER.replace("Mine", "Daylight"))
    (tmp_path / "data" / "netview.db").write_text("secret")
    world = build_world(themes=FolderThemeCatalog(builtin, user))
    return make_client(make_app(world)), user


def test_list_themes_returns_themes_and_user_dir(tmp_path: Path) -> None:
    client, user = make(tmp_path)
    (user / "mine.css").write_text(HEADER)
    response = client.get("/api/v1/themes")
    assert response.status_code == 200
    body = response.json()
    assert body["user_dir"] == str(user)
    assert [t["id"] for t in body["themes"]] == ["daylight", "user-mine"]
    assert body["themes"][1] == {
        "id": "user-mine",
        "name": "Mine",
        "scheme": "light",
        "preview": ["#ffffff", "#eeeeee", "#336699"],
        "source": "user",
        "url": "/themes/user/mine.css",
        "error": None,
    }


def test_a_file_dropped_in_later_shows_up_without_a_restart(tmp_path: Path) -> None:
    client, user = make(tmp_path)
    assert len(client.get("/api/v1/themes").json()["themes"]) == 1
    (user / "late.css").write_text(HEADER)
    assert len(client.get("/api/v1/themes").json()["themes"]) == 2


def test_user_theme_is_served_as_css(tmp_path: Path) -> None:
    client, user = make(tmp_path)
    (user / "mine.css").write_text(HEADER)
    response = client.get("/themes/user/mine.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert "netview-theme" in response.text


def test_path_traversal_is_not_served(tmp_path: Path) -> None:
    client, _ = make(tmp_path)
    for path in (
        "/themes/user/../netview.db",
        "/themes/user/%2e%2e/netview.db",
        "/themes/user/..%2fnetview.db",
    ):
        assert client.get(path).status_code == 404


def test_missing_user_folder_does_not_break_the_app(tmp_path: Path) -> None:
    world = build_world(themes=FolderThemeCatalog(tmp_path / "b", tmp_path / "gone"))
    client = make_client(make_app(world))
    assert client.get("/api/v1/themes").json()["themes"] == []
    assert client.get("/themes/user/x.css").status_code == 404
