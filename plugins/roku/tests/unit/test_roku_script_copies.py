"""The bundled manual-scan scripts match the shared library and are safe to paste."""

from pathlib import Path

import pytest

ROKU_DIR = Path(__file__).resolve().parents[2]
STATIC = ROKU_DIR / "static"
LIB = Path(r"R:\source\scripts\network-tools\scripts\find_rokus.py")


def test_python_copy_is_identical_to_library() -> None:
    if not LIB.exists():
        pytest.skip("shared scripts library not on this machine")
    assert (STATIC / "find_rokus.py").read_bytes() == LIB.read_bytes()


@pytest.mark.parametrize("name", ["find_rokus.py", "find_rokus.ps1"])
def test_copies_are_ascii_and_paste_safe(name: str) -> None:
    text = (STATIC / name).read_bytes().decode("ascii")
    assert not any(line in ("EOF", "'@") for line in text.splitlines())
