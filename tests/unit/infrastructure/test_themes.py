from pathlib import Path

import pytest

from netview.infrastructure.themes import FolderThemeCatalog, parse_theme_header

HEADER = '/* netview-theme name="Harbor" scheme="dark" preview="#0f1e2a,#142838,#6fd1c4" */'


def header(name: str, scheme: str = "dark") -> str:
    return f'/* netview-theme name="{name}" scheme="{scheme}" preview="#000000,#111111,#ffffff" */\n:root{{}}'


def test_parse_theme_header_reads_name_scheme_and_preview() -> None:
    assert parse_theme_header(HEADER) == ("Harbor", "dark", ["#0f1e2a", "#142838", "#6fd1c4"])


def test_parse_theme_header_tolerates_a_bom_and_leading_whitespace() -> None:
    assert parse_theme_header("﻿\n  " + HEADER + "\n:root{}")[0] == "Harbor"


@pytest.mark.parametrize(
    "text",
    [
        '/* netview-theme name="X" scheme="blue" preview="#000000,#111111,#222222" */',
        ":root { --bg: #000; }",
        "",
        '/* netview-theme name="X" scheme="dark" preview="#000000,#111111" */',
        '/* netview-theme name="X" scheme="dark" preview="#000,#111,#222" */',
        '/* netview-theme name="" scheme="dark" preview="#000000,#111111,#222222" */',
        '/* netview-theme scheme="dark" preview="#000000,#111111,#222222" */',
        '/* hello */ /* netview-theme name="X" scheme="dark" preview="#000000,#111111,#222222" */',
    ],
)
def test_parse_theme_header_rejects_bad_headers(text: str) -> None:
    with pytest.raises(ValueError):
        parse_theme_header(text)


def make(tmp_path: Path) -> tuple[FolderThemeCatalog, Path, Path]:
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    return FolderThemeCatalog(builtin, user), builtin, user


def test_builtins_come_first_in_the_fixed_order_then_others_alphabetically(tmp_path: Path) -> None:
    catalog, builtin, user = make(tmp_path)
    for stem in ("zebra", "contrast", "harbor", "alpha", "graphite", "daylight"):
        (builtin / f"{stem}.css").write_text(header(stem.title()))
    (user / "mine.css").write_text(header("Mine", "light"))
    themes = catalog.list()
    assert [t.id for t in themes] == [
        "daylight",
        "graphite",
        "harbor",
        "contrast",
        "alpha",
        "zebra",
        "user-mine",
    ]
    assert themes[0].url == "/static/themes/daylight.css"
    assert themes[0].source == "built-in"
    assert themes[-1].url == "/themes/user/mine.css"
    assert themes[-1].source == "user"
    assert themes[-1].scheme == "light"
    assert themes[-1].error is None


def test_user_themes_are_alphabetical(tmp_path: Path) -> None:
    catalog, _, user = make(tmp_path)
    for stem in ("b", "a", "c"):
        (user / f"{stem}.css").write_text(header(stem))
    assert [t.id for t in catalog.list()] == ["user-a", "user-b", "user-c"]


def test_user_file_gets_user_prefix_and_parsed_fields(tmp_path: Path) -> None:
    catalog, _, user = make(tmp_path)
    (user / "mine.css").write_text(HEADER)
    (theme,) = catalog.list()
    assert (theme.id, theme.name, theme.scheme, theme.source) == ("user-mine", "Harbor", "dark", "user")
    assert theme.preview == ["#0f1e2a", "#142838", "#6fd1c4"]


def test_bad_stems_and_non_css_files_are_skipped(tmp_path: Path) -> None:
    catalog, _, user = make(tmp_path)
    (user / "Bad Name.css").write_text(header("Bad"))
    (user / "Upper.css").write_text(header("Upper"))
    (user / "-lead.css").write_text(header("Lead"))
    (user / "notes.txt").write_text(header("Notes"))
    (user / "sub.css").mkdir()
    (user / "ok-1.css").write_text(header("Ok"))
    assert [t.id for t in catalog.list()] == ["user-ok-1"]


def test_a_file_without_a_valid_header_is_listed_with_an_error(tmp_path: Path) -> None:
    catalog, _, user = make(tmp_path)
    (user / "broken.css").write_text(":root { --bg: #000; }")
    (theme,) = catalog.list()
    assert theme.id == "user-broken"
    assert theme.name == "broken"
    assert theme.error
    assert theme.preview == []


def test_only_the_first_1024_bytes_are_read(tmp_path: Path) -> None:
    catalog, _, user = make(tmp_path)
    (user / "late.css").write_text("/* " + "x" * 1100 + " */\n" + HEADER)
    (theme,) = catalog.list()
    assert theme.error


def test_the_folder_is_read_on_every_call(tmp_path: Path) -> None:
    catalog, _, user = make(tmp_path)
    assert catalog.list() == []
    (user / "new.css").write_text(header("New"))
    assert [t.id for t in catalog.list()] == ["user-new"]


def test_missing_folders_give_an_empty_list(tmp_path: Path) -> None:
    catalog = FolderThemeCatalog(tmp_path / "nope", tmp_path / "nada")
    assert catalog.list() == []
    assert catalog.user_dir() == str(tmp_path / "nada")
