"""Token checks for the solid chip and the colour-free app.css."""

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "netview" / "presentation" / "web" / "static"
THEMES = ("daylight", "graphite", "harbor", "contrast")


def _tokens(css: str) -> dict[str, str]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return {k: v.strip() for k, v in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", css)}


def _lum(h: str) -> float:
    rgb = [int(h[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("name", THEMES)
def test_chip_contrast(name: str) -> None:
    t = _tokens((STATIC / "themes" / f"{name}.css").read_text(encoding="utf-8"))
    bg = t.get("--chip-bg", t["--border-strong"])
    fg = t.get("--chip-fg", t["--text"])
    assert _ratio(bg, fg) >= 4.5, f"{name}: solid chip {fg} on {bg}"


def test_app_css_has_no_colour_literals() -> None:
    css = re.sub(r"/\*.*?\*/", "", (STATIC / "css" / "app.css").read_text(encoding="utf-8"), flags=re.DOTALL)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)
    assert not re.search(r"\brgba?\(", css)
