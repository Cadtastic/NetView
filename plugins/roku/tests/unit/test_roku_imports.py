"""The plugin may import only the netview SDK, the standard library and a few libraries."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROKU_DIR = Path(__file__).resolve().parents[2]

ALLOWED_LIBRARIES = {"fastapi", "pydantic", "sqlalchemy", "alembic"}


def _plugin_files() -> list[Path]:
    return [p for p in sorted(ROKU_DIR.rglob("*.py")) if p.relative_to(ROKU_DIR).parts[0] != "tests"]


def _bad_imports(source: str, label: str) -> list[str]:
    bad: list[str] = []
    for node in ast.walk(ast.parse(source, filename=label)):
        names: list[str] = []
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for name in names:
            top = name.split(".")[0]
            if top in sys.stdlib_module_names or top in ALLOWED_LIBRARIES:
                continue
            if name == "netview.sdk" or name.startswith("netview.sdk."):
                continue
            bad.append(f"{label}:{line} imports {name}")
    return bad


def _offenders() -> list[str]:
    bad: list[str] = []
    for path in _plugin_files():
        bad += _bad_imports(path.read_text(encoding="utf-8"), str(path.relative_to(ROKU_DIR)))
    return bad


def test_plugin_imports_only_the_sdk_and_allowed_libraries() -> None:
    assert _offenders() == []


def test_the_checker_looks_at_the_plugin_modules() -> None:
    names = {p.name for p in _plugin_files()}
    assert {"ecp.py", "service.py", "plugin.py"} <= names


def test_the_checker_flags_a_core_import_and_accepts_the_sdk() -> None:
    assert _bad_imports("import netview.application\n", "x.py") == ["x.py:1 imports netview.application"]
    assert _bad_imports("from netview.sdk import Plugin\n", "x.py") == []
    assert (
        _bad_imports("import os\nfrom .ecp import EcpClient\nfrom fastapi import APIRouter\n", "x.py") == []
    )
