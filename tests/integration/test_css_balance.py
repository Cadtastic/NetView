"""Static checks on the stylesheets: balanced braces, token-only app.css, complete theme files."""

import re
from pathlib import Path

import pytest

from netview.infrastructure.themes import parse_theme_header

STATIC = Path(__file__).resolve().parents[2] / "src" / "netview" / "presentation" / "web" / "static"
APP_CSS = STATIC / "css" / "app.css"
THEMES = {name: STATIC / "themes" / f"{name}.css" for name in ("daylight", "graphite", "harbor", "contrast")}

TOKENS = [
    "--bg", "--surface", "--surface-2", "--surface-hover", "--border", "--border-strong",
    "--text", "--text-muted", "--text-faint",
    "--accent", "--accent-contrast", "--focus",
    "--ok", "--warn", "--bad", "--idle",
    "--series-1", "--series-2", "--series-3", "--series-4",
    "--shadow", "--radius-s", "--radius-m",
]  # fmt: skip

FLOORS = {"daylight": 4.5, "graphite": 4.5, "harbor": 4.5, "contrast": 7.0}


def _strip(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    css = re.sub(r'"(?:\\.|[^"\\])*"', '""', css)
    return re.sub(r"'(?:\\.|[^'\\])*'", "''", css)


def _tokens(css: str) -> dict[str, str]:
    return {k: v.strip() for k, v in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", _strip(css))}


def _lum(hex_colour: str) -> float:
    rgb = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("path", [APP_CSS, *THEMES.values()], ids=lambda p: p.name)
def test_braces_balance_and_never_go_negative(path: Path) -> None:
    depth = 0
    for ch in _strip(path.read_text(encoding="utf-8")):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            assert depth >= 0, f"{path.name}: a closing brace has no opener"
    assert depth == 0, f"{path.name}: {depth} unclosed brace(s)"


def test_app_css_uses_tokens_only() -> None:
    css = _strip(APP_CSS.read_text(encoding="utf-8"))
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not re.search(r"\b(?:rgb|hsl)a?\(", css)


@pytest.mark.parametrize("name", THEMES)
def test_theme_header_parses(name: str) -> None:
    text = THEMES[name].read_text(encoding="utf-8")
    _, scheme, preview = parse_theme_header(text)
    assert scheme == ("light" if name == "daylight" else "dark")
    assert len(preview) == 3


@pytest.mark.parametrize("name", THEMES)
def test_theme_defines_every_token_and_color_scheme(name: str) -> None:
    css = THEMES[name].read_text(encoding="utf-8")
    defined = _tokens(css)
    assert [t for t in TOKENS if t not in defined] == []
    assert re.search(r"color-scheme\s*:\s*(light|dark)\s*;", css)
    assert ":root" in css


@pytest.mark.parametrize("name", THEMES)
def test_theme_text_contrast_meets_floor(name: str) -> None:
    t = _tokens(THEMES[name].read_text(encoding="utf-8"))
    floor = FLOORS[name]
    for fg in ("--text", "--text-muted"):
        for bg in ("--bg", "--surface", "--surface-2"):
            assert _ratio(t[fg], t[bg]) >= floor, f"{name}: {fg} on {bg}"
    assert _ratio(t["--accent-contrast"], t["--accent"]) >= floor, f"{name}: accent-contrast on accent"
    assert _ratio(t["--accent"], t["--surface"]) >= 3.0, f"{name}: accent on surface"
    for status in ("--ok", "--warn", "--bad", "--idle"):
        assert t[status].lower() != t["--accent"].lower()
        assert _ratio(t[status], t["--surface"]) >= 3.0, f"{name}: {status} on surface"


def test_index_links_themes_and_app_css() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert re.search(
        r'<link[^>]*id="theme-light"[^>]*media="\(prefers-color-scheme: light\)"[^>]*daylight\.css', html
    )
    assert re.search(
        r'<link[^>]*id="theme-dark"[^>]*media="\(prefers-color-scheme: dark\)"[^>]*graphite\.css', html
    )
    assert "/static/css/app.css" in html
