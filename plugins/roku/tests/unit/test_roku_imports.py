"""The plugin may import only the netview SDK, the standard library and a few libraries."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROKU_DIR = Path(__file__).resolve().parents[2]

ALLOWED_LIBRARIES = {"fastapi", "pydantic", "sqlalchemy", "alembic"}


def _offenders() -> list[str]:
    bad: list[str] = []
    for path in sorted(ROKU_DIR.rglob("*.py")):
        rel = path.relative_to(ROKU_DIR)
        if rel.parts[0] == "tests":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
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
                bad.append(f"{rel}:{line} imports {name}")
    return bad


def test_plugin_imports_only_the_sdk_and_allowed_libraries() -> None:
    assert _offenders() == []
